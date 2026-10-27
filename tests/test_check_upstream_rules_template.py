"""The distributed check_upstream_rules gate.

Renders wrappers/scripts/check_upstream_rules.py.j2 the way distribute.py does
and runs it against synthetic provider trees. Each MA rule must fail on its
pattern, pass on the accepted alternative, and honour `# ma-allow` only with a
reason.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _wrapper_env import make_env  # noqa: E402


def _render() -> str:
    return (
        make_env()
        .get_template("scripts/check_upstream_rules.py.j2")
        .render(provider_path="provider/", manifest_path="provider/manifest.json")
    )


@pytest.fixture
def run_check(tmp_path: Path):
    script = tmp_path / "scripts" / "check_upstream_rules.py"
    script.parent.mkdir(parents=True)
    script.write_text(_render())

    def run(files: dict[str, str]) -> subprocess.CompletedProcess:
        for rel, text in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        return subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True
        )

    return run


def _code(src: str) -> dict[str, str]:
    return {"provider/mod.py": src}


@pytest.mark.parametrize(
    ("code", "src"),
    [
        ("MA001", "import aiohttp\nasync def f():\n    s = aiohttp.ClientSession()\n"),
        (
            "MA001",
            "from aiohttp import ClientSession as CS\nasync def f():\n    s = CS()\n",
        ),
        ("MA002", "try:\n    x = 1\nexcept Exception:\n    pass\n"),
        ("MA002", "try:\n    x = 1\nexcept:\n    x = 2\n"),
        ("MA002", "try:\n    x = 1\nexcept (ValueError, BaseException):\n    pass\n"),
        ("MA002", "try:\n    x = 1\nexcept Exception as err:\n    pass\n"),
        ("MA003", "def f(log, x):\n    log.info(f'value {x}')\n"),
        ("MA003", "def f(self, x):\n    self.logger.debug('v %s' % x)\n"),
        ("MA003", "def f(LOGGER, x):\n    LOGGER.warning('v {}'.format(x))\n"),
        ("MA003", "def f(self, x):\n    self.logger.log(10, f'v {x}')\n"),
        ("MA004", "import asyncio\nasync def f(c):\n    asyncio.create_task(c)\n"),
        ("MA004", "import asyncio\nasync def f(c):\n    asyncio.ensure_future(c)\n"),
        (
            "MA004",
            "import asyncio\nasync def f(c):\n    asyncio.get_running_loop().create_task(c)\n",
        ),
        ("MA004", "async def f(self, c):\n    self.loop.create_task(c)\n"),
        (
            "MA005",
            "async def f(self):\n    await self.mass.music.database.execute('x')\n",
        ),
    ],
)
def test_violation_fails(run_check, code, src):
    res = run_check(_code(src))
    assert res.returncode == 1, res.stdout
    assert f": {code} " in res.stdout


@pytest.mark.parametrize(
    "src",
    [
        "async def f(self):\n    s = self.mass.http_session\n",
        "try:\n    x = 1\nexcept ValueError:\n    pass\n",
        "try:\n    x = 1\nexcept Exception:\n    raise\n",
        "try:\n    x = 1\nexcept Exception as err:\n    raise RuntimeError from err\n",
        "def f(self):\n    try:\n        x = 1\n    except Exception:\n        self.logger.exception('boom')\n",
        (
            "def f(errors):\n    try:\n        x = 1\n"
            "    except Exception as err:\n        errors.append(err)\n"
        ),
        "def f(self, x):\n    self.logger.info('value %s', x)\n",
        "def f(self, x):\n    self.logger.info('plain message')\n",
        "def f(self, c):\n    self.mass.create_task(c)\n",
        "import asyncio\nasync def f(c):\n    t = asyncio.create_task(c)\n    return t\n",
        "async def f(tg, c):\n    tg.create_task(c)\n",
        "def f(s, x):\n    return f'{x}'\n",
    ],
)
def test_accepted_alternative_passes(run_check, src):
    res = run_check(_code(src))
    assert res.returncode == 0, res.stdout + res.stderr


def test_allow_with_reason_passes(run_check):
    src = (
        "try:\n    x = 1\n"
        "except Exception:  # ma-allow: MA002 best-effort cleanup on shutdown\n"
        "    pass\n"
    )
    assert run_check(_code(src)).returncode == 0


def test_allow_without_reason_fails(run_check):
    src = "try:\n    x = 1\nexcept Exception:  # ma-allow: MA002\n    pass\n"
    res = run_check(_code(src))
    assert res.returncode == 1
    assert "needs a reason" in res.stdout


def test_allow_for_another_code_does_not_apply(run_check):
    src = "try:\n    x = 1\nexcept Exception:  # ma-allow: MA001 wrong code\n    pass\n"
    assert run_check(_code(src)).returncode == 1


def test_only_provider_tree_is_scanned(run_check):
    res = run_check(
        {"tests/test_x.py": "try:\n    x = 1\nexcept Exception:\n    pass\n"}
    )
    assert res.returncode == 0


@pytest.mark.parametrize(
    ("requirements", "ok"),
    [
        (["yandex-music==2.2.0", "aiohttp[speedups]==3.11.0"], True),
        (["pkg==1.0; python_version >= '3.12'"], True),
        (["pkg @ git+https://github.com/o/r@0123456789abcdef"], True),
        (["pkg>=1.0"], False),
        (["pkg"], False),
        (["pkg @ git+https://github.com/o/r@main"], False),
    ],
)
def test_manifest_requirements_pinning(run_check, requirements, ok):
    res = run_check(
        {"provider/manifest.json": json.dumps({"requirements": requirements})}
    )
    assert (res.returncode == 0) is ok, res.stdout
    if not ok:
        assert ": MA006 " in res.stdout
