"""cron 排程時刻不得被 `in_radar_quiet_window` 系統性吞掉。

2026-08-31~09-03 事故:`e47a175` 把平日兩段安靜窗合併成 `2115..2330`(閉區間),
而 `safe-branch-stats.sh` 的 cron 是 `30 23 * * *`——23:30:01 觸發時 hhmm=2330,
剛好落在窗的最後一分鐘。平日(週一~五)這個時刻**每一天**都落在同一段共用的平日
窗裡,所以連續四天被自己的守衛擋掉,只送出 default 優先權的略過通知,直到有人
手動查核才發現;週末因為窗口定義不同才僥倖跑完。

本檔把「cron 時刻」與「安靜窗」都直接從腳本原始碼解析出來比對,而不是各抄一份
到測試裡——腳本改了範圍或排程,下一次執行就會用新內容重新比對,不會悄悄漂移。

**判準的取捨(讀這段再改判準)**:
`lib.sh` 的平日分支是「一段共用窗口」,週一到週五共用同一組數字;因此一個固定
時刻要嘛在平日**全部五天**都撞窗,要嘛**一天都不撞**——不存在「撞三天、兩天沒
事」這種中間態,所以平日判準是零容忍:只要撞了就是這個事故的同一種 bug。
週六與週日則是**各自獨立定義的窗口**(範圍不同),而且 `crontab.example` 裡確實
有工作是刻意設計成「這次剛好落在週末窗內就跳過,沒關係」的機會型工作
(`mid-backfill-publish.sh` 一天四個時段、`monthly-directors.sh` 用 day-of-month
排程、`dow=*` 只是剛好某些年份的 16 日落在週六)——這些不是本次事故的同一種
bug:本次事故是「這支工作要嘛跑、要嘛四天寫進 0 列」的系統性吞沒,不是「一年一
次剛好卡到，隔天/隔月還有機會」。因此週末判準是:**同一支腳本可觸及的週末時刻
(週六+週日合併看)只要還有任何一個不撞窗,就不算違規;只有連週末也全部被吞沒
時才算違規** —— 這才是與本次事故同一等級的系統性吞沒。
另外,若腳本原始碼自己就用 `[ "$dow" -ne N ] && in_radar_quiet_window` 這種寫法
明確排除某個 dow(如 `backfill-margin.sh` 明講「週日 02:30 槽本身就在 quiet 窗內
定義,允許本腳本跑」),代表那個 dow 下呼叫本來就不會執行到,不計入判準——這是
從腳本原始碼解析出來的,不是測試裡手寫的白名單。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_SH = REPO_ROOT / "vps" / "scripts" / "lib.sh"
CRONTAB = REPO_ROOT / "vps" / "scripts" / "crontab.example"
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"

# 一支排程與任何安靜窗邊界之間至少要留的緩衝(分鐘)——本次事故就是卡在邊界上
# (23:30 vs 窗尾 23:30),留邊界才不會被下一次窗口微調重新咬到。
SLOT_MARGIN_MINUTES = 5

WEEKDAY_DOWS = {1, 2, 3, 4, 5}
WEEKEND_DOWS = {6, 7}

# `{ [ "$hhmm" -ge 1405 ] && [ "$hhmm" -le 1545 ]; } && return 0` 這種一行一組
# 的 range,兩個數字都是 lib.sh 裡的字面值——用同一條 regex 直接從原始碼抓,
# 沒有第二份手抄副本會漂移。
RANGE_RE = re.compile(
    r'-ge\s+(\d+)\s*\]\s*&&\s*\[\s*"\$hhmm"\s*-le\s*(\d+)\s*\]'
)

# `min hour dom month dow  bash .../scripts/<name>.sh ...`
# 只吃直接 `bash` 呼叫的那一種——docker run / pgrep 保活行不匹配,天然被排除。
JOB_LINE_RE = re.compile(
    r'^(?P<min>\S+)\s+(?P<hour>\S+)\s+(?P<dom>\S+)\s+(?P<mon>\S+)\s+(?P<dow>\S+)\s+'
    r'bash\s+\S*/scripts/(?P<script>[\w.-]+\.sh)\b'
)

# 腳本原始碼裡明確排除某個 dow 才呼叫的寫法,例如:
#   if [ "$dow" -ne 7 ] && in_radar_quiet_window; then
# 代表 dow=7 這條路根本不會呼叫到函式,不算「在窗內啟動」。
DOW_EXEMPTION_RE = re.compile(
    r'\[\s*"\$dow"\s*-ne\s*(\d)\s*\]\s*&&\s*in_radar_quiet_window'
)

ENV_ASSIGNMENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=\S')
FUNC_DEF_RE = re.compile(r'^[\w-]+\(\)\s*\{')


def _extract_function_body(lib_text, name):
    m = re.search(
        r'^' + re.escape(name) + r'\(\) \{\n(.*?)^\}',
        lib_text,
        re.S | re.M,
    )
    assert m, f"could not locate function {name}() in {LIB_SH}"
    return m.group(1)


def _extract_ranges(block):
    return [(int(a), int(b)) for a, b in RANGE_RE.findall(block)]


def parse_quiet_windows(lib_text):
    """回傳 {dow: [(start_hhmm, end_hhmm), ...]},dow 用 `date +%u`(1=一..7=日)。

    範圍全部用 regex 直接從 `in_radar_quiet_window()` 的原始碼抓,不是另一份
    手打的複製——腳本改了範圍,這裡下一次執行就會抓到新範圍,不會悄悄漂移。
    """
    body = _extract_function_body(lib_text, "in_radar_quiet_window")

    sat_m = re.search(r'if \[ "\$dow" -eq 6 \]; then\n(.*?)\n\s*fi\n', body, re.S)
    sun_m = re.search(r'if \[ "\$dow" -eq 7 \]; then\n(.*?)\n\s*fi\n', body, re.S)
    assert sat_m and sun_m, (
        "could not locate the Saturday (dow==6) / Sunday (dow==7) branches "
        "inside in_radar_quiet_window() — has its shape changed?"
    )

    sat_ranges = _extract_ranges(sat_m.group(1))
    sun_ranges = _extract_ranges(sun_m.group(1))
    # 平日分支沒有自己的 if 包住,是週日分支的 fi 之後、函式結尾之前的其餘內容。
    weekday_block = body[sun_m.end():]
    weekday_ranges = _extract_ranges(weekday_block)

    assert sat_ranges, "parsed zero ranges out of the Saturday branch"
    assert sun_ranges, "parsed zero ranges out of the Sunday branch"
    assert weekday_ranges, "parsed zero ranges out of the weekday branch"

    windows = {dow: list(weekday_ranges) for dow in WEEKDAY_DOWS}
    windows[6] = sat_ranges
    windows[7] = sun_ranges
    return windows


def _parse_field(field, lo, hi):
    if field == "*":
        return list(range(lo, hi + 1))
    values = []
    for part in field.split(","):
        if "-" in part:
            a, b = part.split("-")
            values.extend(range(int(a), int(b) + 1))
        else:
            values.append(int(part))
    return values


def _cron_dow_to_date_u(values):
    """cron 的 dow(0-7,0 與 7 都是週日)換算成 `date +%u`(1=一..7=日)。"""
    return sorted({7 if v in (0, 7) else v for v in values})


def parse_cron_jobs(crontab_text):
    """解析 `bash .../scripts/x.sh` 形式的排程行,回傳 dict 列表。

    跳過 `@reboot`、註解、空行、`CRON_TZ=Asia/Taipei` 這類賦值行,以及不是直接
    `bash` 呼叫的行(docker run、pgrep 保活行)——這些不在「一次略過就是一整輪
    工作沒跑」的語意範圍內。
    """
    jobs = []
    for raw_line in crontab_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue
        if ENV_ASSIGNMENT_RE.match(line):
            continue
        m = JOB_LINE_RE.match(line)
        if not m:
            continue
        minutes = _parse_field(m.group("min"), 0, 59)
        hours = _parse_field(m.group("hour"), 0, 23)
        dows = _cron_dow_to_date_u(_parse_field(m.group("dow"), 0, 7))
        jobs.append({
            "script": m.group("script"),
            "minutes": minutes,
            "hours": hours,
            "dows": dows,
            "dow_field": m.group("dow"),
            "raw": raw_line.strip(),
        })
    return jobs


def scripts_calling_quiet_window():
    """從 vps/scripts/*.sh 的原始碼(grep,而非手抄清單)找出誰真的呼叫這個函式。

    只認「呼叫」——一行純註解提到函式名字(如 weekly-tdcc.sh 特地寫「故意不呼叫
    in_radar_quiet_window」)不算,函式自己的定義行也不算。
    """
    calling = set()
    for path in SCRIPTS_DIR.glob("*.sh"):
        if path.name == "lib.sh":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or FUNC_DEF_RE.match(stripped):
                continue
            code_part = line.split(" #", 1)[0]
            if re.search(r'in_radar_quiet_window\s*(;|&&|\)|$)', code_part):
                calling.add(path.name)
                break
    return calling


def dow_exemptions(script_text):
    """回傳這支腳本原始碼裡,用 `[ "$dow" -ne N ] && in_radar_quiet_window` 明確
    排除、call 根本不會執行到的 dow 集合(1-7,`date +%u` 慣例)。"""
    return {int(m.group(1)) for m in DOW_EXEMPTION_RE.finditer(script_text)}


def _to_minutes(hhmm):
    """把 lib.sh 的 HHMM 整數(如 2330)換算成當日分鐘數,避免小時進位算錯邊界。"""
    h, m = divmod(hhmm, 100)
    return h * 60 + m


def _fmt_hhmm(hhmm):
    h, m = divmod(hhmm, 100)
    return f"{h:02d}:{m:02d}"


DOW_NAME = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}


def find_violation(hhmm, dow, windows, margin_minutes):
    """該 (hhmm, dow) 是否落在窗內、或距任一邊界不足 margin_minutes。

    回傳 (start, end) 表示違規窗口,否則回傳 None。
    """
    slot_min = _to_minutes(hhmm)
    for start, end in windows.get(dow, []):
        lo = _to_minutes(start) - margin_minutes
        hi = _to_minutes(end) + margin_minutes
        if lo <= slot_min <= hi:
            return (start, end)
    return None


def job_combos(job, exempt_dows):
    for dow in job["dows"]:
        if dow in exempt_dows:
            continue
        for hour in job["hours"]:
            for minute in job["minutes"]:
                yield dow, hour * 100 + minute


def evaluate_job(job, windows, exempt_dows, margin_minutes):
    """回傳這個 job 的違規清單(見檔頭的判準說明)。

    平日:零容忍,任一撞窗即違規(平日窗是週一~五共用同一組數字,撞一天等於
    撞五天)。週末:週六＋週日合併看,只有「兩天所有可觸及時刻全部撞窗」才算
    違規——只要還有一個週末時刻是乾淨的,代表這支工作不是被系統性吞沒。
    """
    weekday_failures = []
    weekend_hits = []
    weekend_total = 0
    for dow, hhmm in job_combos(job, exempt_dows):
        violation = find_violation(hhmm, dow, windows, margin_minutes)
        if dow in WEEKDAY_DOWS:
            if violation is not None:
                weekday_failures.append((dow, hhmm, violation))
        else:
            weekend_total += 1
            if violation is not None:
                weekend_hits.append((dow, hhmm, violation))

    failures = list(weekday_failures)
    if weekend_total and len(weekend_hits) == weekend_total:
        failures.extend(weekend_hits)
    return failures


def format_violation(script, dow, hhmm, window, dow_field):
    start, end = window
    day_kind = "weekday" if dow in WEEKDAY_DOWS else f"{DOW_NAME[dow]}(dow={dow})"
    return (
        f"{script} at {_fmt_hhmm(hhmm)} (dow field {dow_field!r}, resolved "
        f"dow={dow}) falls inside {day_kind} quiet window "
        f"{start}..{end} ({_fmt_hhmm(start)}..{_fmt_hhmm(end)})"
    )


class ParseQuietWindowsTest(unittest.TestCase):
    def setUp(self):
        self.lib_text = LIB_SH.read_text(encoding="utf-8")
        self.windows = parse_quiet_windows(self.lib_text)

    def test_all_seven_days_have_ranges(self):
        for dow in range(1, 8):
            self.assertTrue(self.windows.get(dow), f"dow={dow} has no parsed ranges")

    def test_weekday_window_currently_includes_2115_2330(self):
        # 不是重新斷言一份寫死的副本(範圍是上面用 regex 解析出來的),而是確認
        # 「本次事故的具體邊界」此刻確實存在——若有人把它改窄/改寬,這條測試會
        # 先失敗,提醒連帶檢查 crontab.example 的排程有沒有跟著漂移。
        self.assertIn((2115, 2330), self.windows[1])


class CronParsingTest(unittest.TestCase):
    def setUp(self):
        self.crontab_text = CRONTAB.read_text(encoding="utf-8")
        self.jobs = parse_cron_jobs(self.crontab_text)

    def test_parses_a_nonzero_number_of_job_lines(self):
        # 防止 parser 本身壞掉時整份測試靜默通過(等於什麼都沒驗)。
        self.assertGreater(len(self.jobs), 0)

    def test_safe_branch_stats_slot_is_parsed(self):
        names = {j["script"] for j in self.jobs}
        self.assertIn("safe-branch-stats.sh", names)

    def test_mid_backfill_publish_multi_hour_slot_expands(self):
        job = next(j for j in self.jobs if j["script"] == "mid-backfill-publish.sh")
        self.assertEqual(sorted(job["hours"]), [3, 9, 12, 20])
        self.assertEqual(job["minutes"], [0])


class ScriptCallDetectionTest(unittest.TestCase):
    def test_weekly_tdcc_does_not_call_it_despite_mentioning_it_in_a_comment(self):
        # weekly-tdcc.sh 的原始碼裡有一行註解寫著函式名字,說明「故意不呼叫」——
        # 這條測試防止未來把呼叫偵測寫回「純文字比對」而重新產生這個誤判。
        calling = scripts_calling_quiet_window()
        text = (SCRIPTS_DIR / "weekly-tdcc.sh").read_text(encoding="utf-8")
        self.assertIn("in_radar_quiet_window", text)  # 提到了……
        self.assertNotIn("weekly-tdcc.sh", calling)     # ……但沒有真的呼叫


class CronVsQuietWindowTest(unittest.TestCase):
    """核心守則:見檔頭「判準的取捨」。"""

    def setUp(self):
        self.windows = parse_quiet_windows(LIB_SH.read_text(encoding="utf-8"))
        self.jobs = parse_cron_jobs(CRONTAB.read_text(encoding="utf-8"))
        self.guarded_scripts = scripts_calling_quiet_window()
        self.assertTrue(self.guarded_scripts, "found no script calling in_radar_quiet_window")

    def _exempt_dows_for(self, script_name):
        path = SCRIPTS_DIR / script_name
        if not path.exists():
            return set()
        return dow_exemptions(path.read_text(encoding="utf-8"))

    def _guarded_jobs(self, jobs=None):
        jobs = self.jobs if jobs is None else jobs
        return [j for j in jobs if j["script"] in self.guarded_scripts]

    def test_no_guarded_cron_slot_is_swallowed_by_a_quiet_window(self):
        guarded = self._guarded_jobs()
        self.assertTrue(guarded, "no guarded scripts matched any parsed cron job line")
        messages = []
        for job in guarded:
            exempt = self._exempt_dows_for(job["script"])
            for dow, hhmm, violation in evaluate_job(job, self.windows, exempt, SLOT_MARGIN_MINUTES):
                messages.append(format_violation(job["script"], dow, hhmm, violation, job["dow_field"]))
        self.assertEqual(
            messages, [],
            "cron slot(s) are swallowed by a quiet window (or its margin):\n" + "\n".join(messages),
        )

    def test_current_safe_branch_stats_slot_0005_passes(self):
        job = next(j for j in self.jobs if j["script"] == "safe-branch-stats.sh")
        self.assertEqual(job["hours"], [0])
        self.assertEqual(job["minutes"], [5])
        exempt = self._exempt_dows_for(job["script"])
        failures = evaluate_job(job, self.windows, exempt, SLOT_MARGIN_MINUTES)
        self.assertEqual(failures, [], f"current 00:05 slot unexpectedly flagged: {failures}")

    def test_old_2330_slot_regresses_against_current_lib_sh(self):
        # 事故重現:把 safe-branch-stats.sh 的排程換回舊的 `30 23 * * *`,在目前
        # 的 lib.sh 安靜窗定義下,這一格對平日五天必定違規——這就是四天沒跑的
        # 根因。用合成的 crontab 文字做,不動版控裡的真檔案。
        synthetic = (
            "30 23 * * *    bash /home/huang/trever-radar/vps/scripts/"
            "safe-branch-stats.sh >> /home/huang/radar-cron.log 2>&1\n"
        )
        jobs = self._guarded_jobs(parse_cron_jobs(synthetic))
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        exempt = self._exempt_dows_for(job["script"])
        failures = evaluate_job(job, self.windows, exempt, SLOT_MARGIN_MINUTES)
        self.assertTrue(
            failures,
            "expected the old 30 23 * * * slot to be flagged against the current "
            "weekday quiet window — if this fails, either the quiet window shrank "
            "or the regression test itself is broken",
        )
        messages = [format_violation(job["script"], d, h, v, job["dow_field"]) for d, h, v in failures]
        # 訊息形狀符合規格範例(腳本 / 時刻 / 窗),且平日五天全部中獎:
        self.assertEqual(len({d for d, _, _ in failures} & WEEKDAY_DOWS), 5)
        self.assertTrue(any("23:30" in m and "2115..2330" in m for m in messages), messages)


if __name__ == "__main__":
    unittest.main()
