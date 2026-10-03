"""Прогон всех проверок разом. Заменяет цепочку команд в PowerShell:
кириллица в выводе там ломалась.

    python tests/run_all_checks.py
"""
import subprocess
import sys

CHECKS = [
    ("jane_audio", "vendor/irene-va/jane_audio.py"),
    ("jane_time", "vendor/irene-va/jane_time.py"),
    ("jane_wake", "vendor/irene-va/jane_wake.py"),
    ("jane_context", "vendor/irene-va/jane_context.py"),
    ("jane_home", "vendor/irene-va/jane_home.py"),
    ("jane_recipe", "vendor/irene-va/jane_recipe.py"),
    ("jane_habits", "vendor/irene-va/jane_habits.py"),
    ("jane_when", "vendor/irene-va/jane_when.py"),
    ("jane_control", "vendor/irene-va/jane_control.py"),
    ("маршруты", "tests/check_routes.py"),
]


def main():
    bad = 0
    for name, path in CHECKS:
        r = subprocess.run([sys.executable, path], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        tail = ""
        for line in (r.stdout or "").splitlines():
            if "ИТОГ" in line:
                tail = line.strip()
        if r.returncode == 0:
            print("OK    %-12s %s" % (name, tail))
        else:
            bad += 1
            print("FAIL  %-12s %s" % (name, tail or "код %d" % r.returncode))
            for line in (r.stdout or "").splitlines():
                if "FAIL" in line:
                    print("        " + line.strip())
    print()
    print("итого провалов: %d" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())