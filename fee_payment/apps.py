from django.apps import AppConfig


class FeePaymentConfig(AppConfig):
    name = 'fee_payment'

    def ready(self):
        import fee_payment.signals  # noqa