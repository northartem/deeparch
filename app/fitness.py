"""Fitness functions (MVP2 BR-41…44): автоматические проверки архитектурных правил.

Правило = проверяемое утверждение о артефактах сервиса (источник: стандарт DA).
Проверка выполняется по содержимому артефактов в DeepArch; тот же набор правил
экспортируется как CI-пак (gitlab-ci + python-скрипт) для проверки в репозитории.
"""
import json
import re

from .db import exec, now, q


def _eval_rule(rule, art_by_kind):
    kind, check = rule["artifact_kind"], rule["check_kind"]
    params = json.loads(rule["params"] or "{}")
    art = art_by_kind.get(kind) if kind else None
    content = (art.get("content_md") or "") if art else ""
    diagram = (art.get("diagram_code") or "") if art else ""
    if check == "diagram_source":
        ok = bool(diagram.strip())
        return ok, "исходник диаграммы присутствует" if ok else "исходник диаграммы отсутствует"
    if check == "minlen":
        need = int(params.get("value", 200))
        ok = len(content.strip()) >= need
        return ok, f"объём {len(content.strip())} / {need} символов"
    if check == "contains":
        values = params.get("value") or []
        if isinstance(values, str):
            values = [values]
        missing = [v for v in values if v.lower() not in content.lower()]
        ok = not missing
        return ok, "найдено всё требуемое" if ok else f"отсутствует: {', '.join(missing)}"
    if check == "regex":
        pat = params.get("value", "")
        m = re.search(pat, content, re.IGNORECASE)
        need_n = int(params.get("count", 1))
        if need_n > 1:
            found = len(re.findall(pat, content, re.IGNORECASE))
            ok = found >= need_n
            return ok, f"совпадений {found} / {need_n}"
        return bool(m), f"паттерн {pat!r} {'найден' if m else 'не найден'}"
    return False, f"неизвестный тип проверки: {check}"


def run_fitness(service, user):
    arts = q("SELECT kind, content_md, diagram_code FROM artifacts WHERE service_id=?",
             (service["id"],))
    art_by_kind = {a["kind"]: dict(a) for a in arts}
    rules = [r for r in q("SELECT * FROM fitness_rules WHERE active=1 ORDER BY id")]
    results, passed, failed, warned = [], 0, 0, 0
    for r in rules:
        if r["artifact_kind"] and r["artifact_kind"] not in art_by_kind:
            verdict, detail = "fail", "артефакт отсутствует"
        else:
            ok, detail = _eval_rule(r, art_by_kind)
            verdict = "pass" if ok else ("warn" if r["severity"] == "warning" else "fail")
        results.append({"rule_id": r["id"], "name": r["name"], "artifact": r["artifact_kind"],
                        "severity": r["severity"], "verdict": verdict, "detail": detail})
        passed += verdict == "pass"; failed += verdict == "fail"; warned += verdict == "warn"
    exec("INSERT INTO fitness_runs(service_id,results,passed,failed,warned,created_by,created_at)"
         " VALUES(?,?,?,?,?,?,?)",
         (service["id"], json.dumps(results, ensure_ascii=False), passed, failed, warned,
          user["username"], now()))
    return {"results": results, "passed": passed, "failed": failed, "warned": warned,
            "verdict": "pass" if failed == 0 else "fail"}


def ci_pack(service):
    """CI-пак: gitlab-ci job + автономный python-скрипт с теми же правилами."""
    rules = q("SELECT * FROM fitness_rules WHERE active=1 ORDER BY id")
    script = ["#!/usr/bin/env python3",
              f'"""Fitness-check для {service["code"]} — сгенерировано DeepArch.',
              "Правила синхронизированы со стандартом DA. Проверяет файлы в репозитории.",
              '"""', "import re, sys", "RULES = ["]
    for r in rules:
        params = json.loads(r["params"] or "{}")
        path = params.get("path") or {"vision_c4": "arch/context-diagram.dsl",
                                      "deployment": "deployment/docker-compose.yml",
                                      "api": "api/openapi.yaml",
                                      "adr": "adr/README.md",
                                      "data_model": "db/er-diagram.dbml",
                                      "nfr_security": "nfr/README.md",
                                      "config_build": "docker-compose.yml"}.get(r["artifact_kind"], ".")
        script.append(f'    {{"name": {r["name"]!r}, "kind": {r["check_kind"]!r}, '
                      f'"path": {path!r}, "params": {params!r}}},')
    script.append("]")
    script += [
        "", "fails = []",
        "for rule in RULES:",
        "    try: text = open(rule['path'], encoding='utf-8').read()",
        "    except OSError: fails.append(f\"{rule['name']}: файл {rule['path']} не найден\"); continue",
        "    k, p = rule['kind'], rule['params']",
        "    if k == 'contains':",
        "        vals = p.get('value', [])",
        "        vals = [vals] if isinstance(vals, str) else vals",
        "        miss = [v for v in vals if v.lower() not in text.lower()]",
        "        if miss: fails.append(f\"{rule['name']}: отсутствует {', '.join(miss)}\")",
        "    elif k == 'regex':",
        "        if not re.search(p.get('value', ''), text, re.I):",
        "            fails.append(f\"{rule['name']}: паттерн не найден\")",
        "    elif k == 'minlen':",
        "        if len(text.strip()) < p.get('value', 200):",
        "            fails.append(f\"{rule['name']}: слишком мало содержимого\")",
        "print('fitness:', 'PASS' if not fails else 'FAIL')",
        "for f in fails: print(' -', f)",
        "sys.exit(1 if fails else 0)", ""]
    python = "\n".join(script)
    yaml = (f"fitness:{service['code'].lower()}:\n"
            "  stage: test\n"
            "  image: python:3.12-alpine\n"
            "  script:\n"
            f"    - python3 fitness/{service['code'].lower()}_check.py\n"
            "  allow_failure: false\n")
    return yaml, python
