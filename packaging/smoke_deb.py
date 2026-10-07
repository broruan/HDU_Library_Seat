"""Exercise the installed deb as a normal user, outside the source checkout."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main() -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    installed_package = Path("/usr/lib/hdu-library-seat/hdu_seat")
    assert (installed_package / "notification.py").is_file()
    email_fields = {
        "email_enabled", "smtp_host", "smtp_port", "smtp_security", "smtp_username",
        "smtp_password", "smtp_password_set", "email_sender", "email_recipient",
    }
    placeholder_password = "smoke-test-authorization-placeholder"

    def post_config(url: str, config: dict) -> dict:
        request = urllib.request.Request(url + "/api/config", data=json.dumps(config).encode(),
                                         headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=5) as response:
            return json.load(response)

    with tempfile.TemporaryDirectory(prefix="hdu-installed-test-") as temporary:
        work = Path(temporary)
        browser = work / "browser.py"
        browser.write_text("import pathlib, sys\npathlib.Path(__file__).with_suffix('.url').write_text(sys.argv[1])\n")
        env = dict(os.environ, HOME=str(work), XDG_CONFIG_HOME=str(work / "settings"),
                   BROWSER=f"/usr/bin/python3 {browser} %s", DISPLAY=":99")
        env.pop("HDU_LIBRARY_COOKIE", None)
        env.pop("PYTHONPATH", None)
        for attempt in range(2):
            log_path = work / f"run-{attempt}.log"
            with log_path.open("wb") as log:
                command = ["/usr/bin/hdu-library-seat"]
                if attempt == 0:
                    command.append("--no-browser")
                process = subprocess.Popen(command, cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        match = re.search(rb"http://127\.0\.0\.1:\d+", log_path.read_bytes())
                        if match:
                            break
                        if process.poll() is not None:
                            raise RuntimeError(log_path.read_text())
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Installed app failed to start")
                    url = match[0].decode()
                    with opener.open(url, timeout=5) as response:
                        assert response.read() == Path("/usr/lib/hdu-library-seat/hdu_seat/web/index.html").read_bytes()
                    with opener.open(url + "/api/config", timeout=5) as response:
                        config = json.load(response)
                    assert config["cookie"] == ("" if attempt == 0 else "smoke-test-placeholder")
                    assert email_fields <= config.keys()
                    assert config["smtp_password"] == ""
                    if attempt == 0:
                        assert config["email_enabled"] is False
                        assert config["smtp_password_set"] is False
                        config.update({
                            "email_enabled": False,
                            "smtp_host": "smtp.example.invalid",
                            "smtp_port": 465,
                            "smtp_security": "ssl",
                            "smtp_username": "smoke-sender@example.invalid",
                            "smtp_password": placeholder_password,
                            "email_sender": "",
                            "email_recipient": "",
                        })
                        saved = post_config(url, config)
                        assert saved["cookie"] == ""
                        assert saved["email_enabled"] is False
                        assert saved["smtp_password"] == ""
                        assert saved["smtp_password_set"] is True
                        assert placeholder_password not in json.dumps(saved)
                        config = saved
                        config["cookie"] = "smoke-test-placeholder"
                        saved = post_config(url, config)
                        assert saved["cookie"] == config["cookie"]
                        assert saved["smtp_password"] == ""
                        assert saved["smtp_password_set"] is True
                        config_path = work / "settings/hdu-library-seat/config.json"
                        persisted = json.loads(config_path.read_text())
                        assert persisted["cookie"] == config["cookie"]
                        assert persisted["email"]["password"] == placeholder_password
                        assert persisted["email"]["enabled"] is False
                        assert config_path.parent.stat().st_mode & 0o777 == 0o700
                    else:
                        assert config["email_enabled"] is False
                        assert config["smtp_host"] == "smtp.example.invalid"
                        assert config["smtp_username"] == "smoke-sender@example.invalid"
                        assert config["smtp_password_set"] is True
                        assert browser.with_suffix(".url").read_text() == url
                    # Missing host fails validation before any SMTP connection.
                    invalid_email = dict(config, smtp_host="", smtp_password="")
                    request = urllib.request.Request(url + "/api/email/test", data=json.dumps(invalid_email).encode(),
                                                     headers={"Content-Type": "application/json"})
                    try:
                        with opener.open(request, timeout=5):
                            raise AssertionError("An unconfigured SMTP test unexpectedly succeeded")
                    except urllib.error.HTTPError as error:
                        assert error.code == 400
                        failed = json.load(error)
                    assert failed["status"] == "failed"
                    assert failed["message"] == "请填写有效的 SMTP 服务器地址"
                    assert failed["error"] == failed["message"]
                    assert failed["at"]
                    assert placeholder_password not in json.dumps(failed)
                    with opener.open(url + "/api/status", timeout=5) as response:
                        status = json.load(response)
                    assert status["running"] is False
                    assert status["notification"]["status"] == "failed"
                    assert status["config"]["smtp_password"] == ""
                    assert status["config"]["smtp_password_set"] is True
                    assert placeholder_password not in json.dumps(status)
                finally:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise
                assert process.returncode == 0, log_path.read_text()
                print(f"PASS installed launch {attempt + 1}: webpage, config, email API validation and persistence, browser dispatch, clean shutdown")


if __name__ == "__main__":
    main()
