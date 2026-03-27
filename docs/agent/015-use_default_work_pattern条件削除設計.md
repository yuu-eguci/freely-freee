# 015 use_default_work_pattern 条件削除設計

## 要望

"指定の月に勤怠を詰め込む" 機能の修正。

- `use_default_work_pattern` を見て処理対象かどうかを決めているが、これは関係なかった
- この条件を削除する
- `normal_day` かどうかだけ見れば OK

## 詳細設計
### 1. 今の実装で `use_default_work_pattern` を参照してる箇所
- 相棒、参照してるのは `app/actions/bulk_attendance.py` の `_process_date` だけだよ。
- 具体的には `get_work_record` の `body` から `day_pattern` と `use_default_work_pattern` を取り出してる。
- そのあと条件分岐が 2 段ある。
    - `day_pattern != "normal_day"` のときは `skipped` にしてる。
    - `use_default_work_pattern is not True` のときも `skipped` にしてる。
- 今回削る対象は 2 段目の `use_default_work_pattern` 判定と、それに紐づく `SKIP` ログ ( `reason=use_default_work_pattern_false` ) だよ。

### 2. 削除後の条件 ( `normal_day` のみ )
- あたしの変更方針はシンプルで、処理対象判定は `day_pattern == "normal_day"` だけにする。
- `use_default_work_pattern` の読み取り自体を削除する。
- `day_pattern` が `normal_day` なら、そのまま有給判定 -> 勤怠登録 -> 必要ならタグ付与まで進める。
- `day_pattern` が `normal_day` 以外なら、今までどおり `skipped` にする。

### 3. 影響範囲 ( テスト込み )
- コード参照の影響範囲は `app/actions/bulk_attendance.py` の `_process_date` のみ。
- `grep` で見た限り、`use_default_work_pattern` を直接参照してるのはここだけで、他モジュールには波及しない。
- テストの直接影響は `tests/test_bulk_attendance_paid_holidays.py`。
    - 既存の `Fake` client は `use_default_work_pattern=True` を返してるだけなので、判定削除後も既存テストの主目的 ( 有給 full / half の挙動 ) は維持される。
    - ただし回帰防止のため、設計としては `_process_date` 向けに次の観点を追加する想定。
        - `day_pattern="normal_day"` かつ `use_default_work_pattern=False` でも `success` になること。
        - `day_pattern` が `normal_day` 以外なら、`use_default_work_pattern` の値に関係なく `skipped` になること。

## レビュー
