# aurora-alert

墨尔本极光推送：GitHub Actions 定时查 NOAA 太阳风/Kp 数据，有机会时推送到手机 ntfy。

- 夜间每15分钟：实时预警（Kp≥6 / Kp≥7 / Bz 转南+高速太阳风）
- 每天中午：未来3天地磁暴预报
- 需要仓库 Secret：`NTFY_TOPIC`
- 手动测试：Actions → aurora-alert → Run workflow → mode = test
