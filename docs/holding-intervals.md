# 绝对持有期与广义持有期

两种区间都只读取冻结的完整PDF路径账本，起点必须是明确的`turn_hold`，`not_mentioned`延续最近明确状态。

- 绝对持有允许`turn_hold/hold`；`strong_watch/watch/weak_watch/turn_weak/exit/avoid`结束。
- 广义持有允许`turn_hold/hold/strong_watch`；`watch/weak_watch/turn_weak/exit/avoid`结束。
- 正式收益只使用`complete_eod`收盘；服务器缓存盘中价只能形成单列参考收益。

版本化合同见`config/holding_interval_policy_v1.json`。
