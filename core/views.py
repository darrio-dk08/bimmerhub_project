from django.shortcuts import render


def home(request):
    """Display the public BimmerHub homepage."""
    return render(request, "core/home.html")