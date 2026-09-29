<?php
/**
 * Plugin Name: درگاه کارت به کارت هوشمند بلوبات برای ووکامرس
 * Plugin URI: https://pay.8cloud.ir/wordpress
 * Description: درگاه پرداخت کارت‌به‌کارت تمام خودکار و لحظه‌ای بلوبانک ویژه ووکامرس (بدون نیاز به پیامک‌خوان یا گوشی فیزیکی)
 * Version: 1.0.0
 * Author: تیم توسعه بلوبات (BluBot)
 * Author URI: https://pay.8cloud.ir
 * Text Domain: wc-blubot-gateway
 * Domain Path: /languages
 */

if (!defined('ABSPATH')) {
    exit;
}

add_action('plugins_loaded', 'init_wc_blubot_gateway');

function init_wc_blubot_gateway() {
    if (!class_exists('WC_Payment_Gateway')) {
        return;
    }

    class WC_Gateway_BluBot extends WC_Payment_Gateway {

        public function __construct() {
            $this->id                 = 'blubot';
            $this->icon               = apply_filters('woocommerce_blubot_icon', '');
            $this->has_fields         = false;
            $this->method_title       = 'کارت‌به‌کارت هوشمند بلوبات';
            $this->method_description = 'درگاه پرداخت کارت‌به‌کارت هوشمند با تایید لحظه‌ای واریزی‌ها از طریق نشست فعال بلوبانک.';

            $this->init_form_fields();
            $this->init_settings();

            $this->title       = $this->get_option('title');
            $this->description = $this->get_option('description');
            $this->api_key     = $this->get_option('api_key');
            $this->api_url     = untrailingslashit($this->get_option('api_url', 'https://pay.8cloud.ir/api/v1'));
            $this->sandbox     = 'yes' === $this->get_option('sandbox');

            add_action('woocommerce_update_options_payment_gateways_' . $this->id, array($this, 'process_admin_options'));
            add_action('woocommerce_api_wc_gateway_blubot', array($this, 'handle_webhook_callback'));
        }

        public function init_form_fields() {
            $this->form_fields = array(
                'enabled' => array(
                    'title'   => 'فعال‌سازی',
                    'type'    => 'checkbox',
                    'label'   => 'فعال‌سازی درگاه کارت‌به‌کارت بلوبات',
                    'default' => 'yes'
                ),
                'title' => array(
                    'title'       => 'عنوان درگاه',
                    'type'        => 'text',
                    'description' => 'عنوانی که خریدار در صفحه تسویه‌حساب مشاهده می‌کند.',
                    'default'     => 'کارت‌به‌کارت هوشمند بلوبات',
                    'desc_tip'    => true,
                ),
                'description' => array(
                    'title'       => 'توضیحات درگاه',
                    'type'        => 'textarea',
                    'description' => 'توضیحات تکمیلی که در صفحه پرداخت نمایش داده می‌شود.',
                    'default'     => 'پرداخت مستقیم و آنی کارت‌به‌کارت با تایید لحظه‌ای واریز بدون نیاز به ارسال فیش.',
                ),
                'api_key' => array(
                    'title'       => 'کلید API (Live Key)',
                    'type'        => 'text',
                    'description' => 'کلید زنده یا تستی خود را از ربات یا مینی‌اپ تلگرام بلوبات دریافت و اینجا وارد کنید.',
                    'default'     => '',
                ),
                'api_url' => array(
                    'title'       => 'آدرس سرور بلوبات',
                    'type'        => 'text',
                    'description' => 'آدرس API سرور بلوبات (پیش‌فرض: https://pay.8cloud.ir/api/v1)',
                    'default'     => 'https://pay.8cloud.ir/api/v1',
                ),
                'sandbox' => array(
                    'title'   => 'حالت آزمایشی (Sandbox)',
                    'type'    => 'checkbox',
                    'label'   => 'فعال‌سازی حالت شبیه‌سازی و تست بدون واریز واقعی',
                    'default' => 'no'
                )
            );
        }

        public function process_payment($order_id) {
            $order = wc_get_order($order_id);

            // Determine currency (Rials vs Tomans)
            $currency = get_woocommerce_currency();
            $order_total = $order->get_total();
            
            if ($currency === 'IRT' || $currency === 'TOMAN' || $currency === 'toman') {
                $amount_rials = (int)($order_total * 10);
            } else {
                $amount_rials = (int)$order_total;
            }

            $endpoint = $this->sandbox ? "{$this->api_url}/sandbox/invoices/create" : "{$this->api_url}/invoices/create";

            $response = wp_remote_post($endpoint, array(
                'method'    => 'POST',
                'timeout'   => 15,
                'headers'   => array(
                    'Content-Type' => 'application/json',
                    'X-API-Key'    => $this->api_key,
                ),
                'body'      => wp_json_encode(array(
                    'amount'      => $amount_rials,
                    'order_id'    => (string)$order_id,
                    'description' => sprintf('سفارش #%s در %s', $order_id, get_bloginfo('name'))
                ))
            ));

            if (is_wp_error($response)) {
                wc_add_notice('خطا در برقراری ارتباط با درگاه بلوبات: ' . $response->get_error_message(), 'error');
                return array('result' => 'fail');
            }

            $body = json_decode(wp_remote_retrieve_body($response), true);

            if (empty($body['success']) || empty($body['payment_link'])) {
                $error_msg = !empty($body['message']) ? $body['message'] : 'خطای نامشخص در ایجاد فاکتور';
                wc_add_notice('خطای درگاه بلوبات: ' . $error_msg, 'error');
                return array('result' => 'fail');
            }

            // Save BluBot Invoice details in Order Meta
            $order->update_meta_data('_blubot_invoice_id', $body['invoice_id']);
            $order->update_meta_data('_blubot_final_amount', $body['final_amount']);
            $order->update_meta_data('_blubot_card_number', $body['card_number']);
            $order->save();

            // Clear Cart and Redirect to BluBot Checkout Page
            WC()->cart->empty_cart();

            return array(
                'result'   => 'success',
                'redirect' => $body['payment_link']
            );
        }

        public function handle_webhook_callback() {
            $input = file_get_contents('php://input');
            $data  = json_decode($input, true);

            if (empty($data) || empty($data['invoice_id']) || empty($data['status'])) {
                status_header(400);
                wp_send_json(array('error' => 'Invalid webhook payload'));
                exit;
            }

            if ($data['status'] === 'PAID') {
                $invoice_id = $data['invoice_id'];

                // Find WooCommerce Order by Invoice ID
                $orders = wc_get_orders(array(
                    'meta_key'   => '_blubot_invoice_id',
                    'meta_value' => $invoice_id,
                    'limit'      => 1
                ));

                if (!empty($orders)) {
                    $order = $orders[0];
                    if (!$order->is_paid()) {
                        $payer_info = sprintf(
                            'تایید خودکار واریز کارت‌به‌کارت بلوبات. واریزکننده: %s | کارت: %s | پیگیری: %s',
                            !empty($data['payer_name']) ? $data['payer_name'] : 'نامشخص',
                            !empty($data['payer_card']) ? $data['payer_card'] : 'نامشخص',
                            !empty($data['tracking_number']) ? $data['tracking_number'] : '-'
                        );
                        $order->payment_complete($invoice_id);
                        $order->add_order_note($payer_info);
                    }
                }
            }

            status_header(200);
            wp_send_json(array('success' => true));
            exit;
        }
    }

    add_filter('woocommerce_payment_gateways', 'add_blubot_gateway_class');
    function add_blubot_gateway_class($gateways) {
        $gateways[] = 'WC_Gateway_BluBot';
        return $gateways;
    }
}
