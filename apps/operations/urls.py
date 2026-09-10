from django.urls import path
from . import views
from .razorpay_views import razorpay_verify

app_name = "operations"

urlpatterns = [
    path("grinding/", views.grinding_board, name="grinding_board"),
    path("grinding/new/", views.grinding_create, name="grinding_create"),
    path("grinding/<int:pk>/", views.order_detail, name="order_detail"),
    path("grinding/<int:pk>/edit/", views.grinding_edit, name="grinding_edit"),
    path("grinding/<int:pk>/delete/", views.grinding_delete, name="grinding_delete"),
    path("grinding/<int:pk>/status/", views.order_status, name="order_status"),
    path("grinding/<int:pk>/settle/", views.settle_bill, name="settle_bill"),
    path("grinding/<int:pk>/buyback/", views.order_buyback, name="order_buyback"),
    path("grinding/<int:pk>/request-qr/", views.request_qr_payment, name="request_qr_payment"),
    path("payments/razorpay/verify/", razorpay_verify, name="razorpay_verify"),
    path("payments/<str:reference>/status/", views.payment_status, name="payment_status"),
    path("rate-card/", views.rate_card, name="rate_card"),
    path("buyback/", views.buyback, name="buyback"),
    path("production/", views.production, name="production"),
    path("wastage/", views.wastage, name="wastage"),
    path("utilities/", views.utilities, name="utilities"),
]
