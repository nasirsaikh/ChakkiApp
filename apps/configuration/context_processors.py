from .models import ChakkiSettings

def chakki_settings(request):
    try:
        return {"chakki": ChakkiSettings.load()}
    except Exception:
        return {"chakki": None}
