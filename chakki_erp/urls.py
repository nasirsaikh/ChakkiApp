from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from apps.operations.razorpay_views import razorpay_webhook
from apps.operations.views import qr_webhook

urlpatterns = [
    path("api/v1/payments/qr-webhook/", qr_webhook, name="qr_payment_webhook"),
    path("api/v1/payments/razorpay/webhook/", razorpay_webhook, name="razorpay_payment_webhook"),
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("apps.core.urls")),
    path("customers/", include("apps.customers.urls")),
    path("accounting/", include("apps.accounting.urls")),
    path("operations/", include("apps.operations.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("workforce/", include("apps.workforce.urls")),
    path("settings/", include("apps.configuration.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
