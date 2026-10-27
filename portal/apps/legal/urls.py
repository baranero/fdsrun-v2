from django.urls import path

from .views import page

app_name = "legal"
urlpatterns = [
    path("regulamin/", page("regulamin"), name="terms"),
    path("polityka-prywatnosci/", page("prywatnosc"), name="privacy"),
    path("cookies/", page("cookies"), name="cookies"),
    path("umowa-powierzenia/", page("dpa"), name="dpa"),
]
