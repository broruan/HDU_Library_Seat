"""Exercise the installed deb as a normal user, outside the source checkout."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import urllib.request


def main() -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
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
                    if attempt == 0:
                        config["cookie"] = "smoke-test-placeholder"
                        request = urllib.request.Request(url + "/api/config", data=json.dumps(config).encode(),
                                                         headers={"Content-Type": "application/json"})
                        with opener.open(request, timeout=5) as response:
                            assert json.load(response)["cookie"] == config["cookie"]
                        config_path = work / "settings/hdu-library-seat/config.json"
                        assert json.loads(config_path.read_text())["cookie"] == config["cookie"]
                        assert config_path.parent.stat().st_mode & 0o777 == 0o700
                    else:
                        assert browser.with_suffix(".url").read_text() == url
                    with opener.open(url + "/api/status", timeout=5) as response:
                        assert json.load(response)["running"] is False
                finally:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise
                assert process.returncode == 0, log_path.read_text()
                print(f"PASS installed launch {attempt + 1}: webpage, config, browser dispatch, clean shutdown")


if __name__ == "__main__":
    main()
