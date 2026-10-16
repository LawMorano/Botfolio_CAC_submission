"""Route groups and compatibility registration."""


def register_blueprint_compat(app, blueprint):
    """Register a Blueprint while retaining the app's established endpoints."""
    app.register_blueprint(blueprint)
    prefix = f"{blueprint.name}."
    rules = [rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith(prefix)]
    for rule in rules:
        endpoint = rule.endpoint[len(prefix):]
        app.add_url_rule(
            rule.rule,
            endpoint=endpoint,
            view_func=app.view_functions[rule.endpoint],
            defaults=rule.defaults,
            methods=rule.methods,
        )
