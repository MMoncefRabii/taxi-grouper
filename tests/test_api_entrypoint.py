def test_root_api_reexports_service_app_and_its_routes():
    import api
    from src.api.service import app as service_app

    expected_routes = [
        (method, route.path)
        for route in service_app.routes
        for method in sorted(getattr(route, "methods", set()))
    ]
    actual_routes = [
        (method, route.path)
        for route in api.app.routes
        for method in sorted(getattr(route, "methods", set()))
    ]

    assert api.app is service_app
    assert actual_routes == expected_routes
    assert len(actual_routes) == len(set(actual_routes))
