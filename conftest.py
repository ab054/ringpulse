"""Root conftest: loads the plugin that records test outcomes (reruns, flakes) and applies quarantine.yaml."""
pytest_plugins = ["ci.test_results_plugin"]
