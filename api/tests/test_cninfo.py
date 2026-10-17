from app.data.cninfo import clean_title, exchange_column, pick_full_report


def ann(title: str, time_ms: int) -> dict:
    return {"announcementTitle": title, "announcementTime": time_ms}


def test_exchange_column():
    assert exchange_column("600519") == "sse"
    assert exchange_column("000333") == "szse"
    assert exchange_column("300750") == "szse"


def test_clean_title_strips_highlight_tags():
    assert clean_title("贵州茅台<em>2023年年度报告</em>") == "贵州茅台2023年年度报告"


def test_picks_full_report_and_ignores_summary_and_english():
    announcements = [
        ann("2023年年度报告摘要", 1),
        ann("2023年年度报告（英文版）", 2),
        ann("2023年年度报告", 3),
    ]
    assert pick_full_report(announcements, 2023)["announcementTime"] == 3


def test_accepts_title_without_repeated_year_character():
    # 招商银行 titles its report "2025年度报告", not "2025年年度报告"
    announcements = [ann("招商银行股份有限公司2025年度报告摘要", 1), ann("招商银行股份有限公司2025年度报告", 2)]
    assert pick_full_report(announcements, 2025)["announcementTime"] == 2


def test_ignores_other_years_and_half_year_reports():
    announcements = [ann("2022年年度报告", 1), ann("2023年半年度报告", 2)]
    assert pick_full_report(announcements, 2023) is None


def test_reissued_report_wins_over_original():
    announcements = [ann("2023年年度报告", 1), ann("2023年年度报告（更新后）", 5)]
    assert pick_full_report(announcements, 2023)["announcementTime"] == 5


def test_cancelled_notice_is_ignored():
    announcements = [ann("2023年年度报告", 1), ann("关于取消2023年年度报告的公告", 9)]
    assert pick_full_report(announcements, 2023)["announcementTime"] == 1
