from django.urls import path
from . import views
app_name = "inventory"
urlpatterns = [
    path("stock/", views.stock, name="stock"),
    path("purchases/", views.purchases, name="purchases"),
    path("sales/", views.sales, name="sales"),
    path("suppliers/", views.suppliers, name="suppliers"),
]
