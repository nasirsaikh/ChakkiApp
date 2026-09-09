from django.urls import path
from . import views
app_name = "operations"
urlpatterns = [
    path("grinding/", views.grinding_board, name="grinding_board"),
    path("grinding/new/", views.grinding_create, name="grinding_create"),
    path("grinding/<int:pk>/", views.order_detail, name="order_detail"),
    path("grinding/<int:pk>/status/", views.order_status, name="order_status"),
    path("grinding/<int:pk>/request-qr/", views.request_qr_payment, name="request_qr_payment"),
    path("payments/<str:reference>/status/", views.payment_status, name="payment_status"),
    path("rate-card/", views.rate_card, name="rate_card"),
    path("buyback/", views.buyback, name="buyback"),
    path("production/", views.production, name="production"),
    path("wastage/", views.wastage, name="wastage"),
    path("utilities/", views.utilities, name="utilities"),
]
