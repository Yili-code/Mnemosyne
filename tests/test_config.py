import vocab_bot.config as config


def test_review_size_defaults_to_ten(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "load_dotenv", lambda: False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "123456789")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("CRON_SECRET", "test-cron-secret")
    monkeypatch.delenv("REVIEW_SIZE", raising=False)

    assert config.Settings.from_env().review_size == 10
