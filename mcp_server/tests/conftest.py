"""No fixtures needed yet: app.core.config.Settings defaults mcp_mock_mode
to True, which every tool's execute_* function checks first — so simply not
setting real-mode env vars in the test environment is enough to guarantee
every test here exercises the mock path, no real network calls, no real
credentials needed. get_settings() is @lru_cache'd; tests don't override
settings, so that cache never needs clearing between tests here.
"""
