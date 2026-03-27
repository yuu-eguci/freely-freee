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

### 1回目 (2026-03-27)

実装コードとテストコードを確認して、以下の指摘をまとめたよ。

#### 指摘1: 変更対象コードの特定が正確

- `app/actions/bulk_attendance.py:244-260` を見たら、設計どおり 2 段の条件分岐があって、 `use_default_work_pattern` の判定 (255-260行目) が今回の削除対象として正しく特定されてる。
- コード上も `day_pattern` と `use_default_work_pattern` を `body.get()` で取得してるのを確認した (243-246行目)。
- この設計書の「今の実装で `use_default_work_pattern` を参照してる箇所」のセクションはコードと一致してるよ。

#### 指摘2: テストの Fake client が `use_default_work_pattern=True` を返してる点

- `tests/test_bulk_attendance_paid_holidays.py:46-54` を見ると、 `_FakeHrApiClientForProcessDate.get_work_record()` が固定で `use_default_work_pattern=True` を返してる。
- 設計書 30 行目に「既存の `Fake` client は `use_default_work_pattern=True` を返してるだけなので、判定削除後も既存テストの主目的 ( 有給 full / half の挙動 ) は維持される。」って書いてあるのはその通り。
- でも、設計書 31-33 行目に「ただし回帰防止のため、設計としては `_process_date` 向けに次の観点を追加する想定。」って書いてあるんだけど、実際にはテストコードに追加するべき観点が「想定」って言葉でぼやかされてる。
- これは実装担当者向けに、もっと具体的に「新規テストケースを追加する」って明示したほうがいいと思うw

#### 指摘3: テストケースの追加観点をもっと具体的に

設計書 31-33 行目に 2 つのテスト観点が書いてあるけど、もうちょっと具体的に書いたほうが実装しやすいよね。

- 「`day_pattern="normal_day"` かつ `use_default_work_pattern=False` でも `success` になること。」
    - これは `_FakeHrApiClientForProcessDate` の `get_work_record()` を修正して、 `use_default_work_pattern=False` を返すバージョンを作って、 `_process_date()` を呼んだときに `result=="success"` になることを確認する、っていう感じかな。
    - でも、このテストケースの名前とか、どこに追加するかとか、そういうのも設計書に入れたほうが親切だと思う♡
- 「`day_pattern` が `normal_day` 以外なら、`use_default_work_pattern` の値に関係なく `skipped` になること。」
    - これも同様に、 `day_pattern="holiday"` とか `"legal_holiday"` とかのパターンで、 `use_default_work_pattern` が `True` / `False` のどちらでも `skipped` になることを確認する、っていうテストだよね。
    - 複数パターンをテストするなら、 `parameterized` とか使うかもしれないけど、そこまで書くかどうかは実装担当者次第かなw

#### 指摘4: ログ出力の削除も忘れずに

- `app/actions/bulk_attendance.py:255-260` を見ると、 `use_default_work_pattern is not True` のときに `[SKIP]` ログを出力してる。
- 設計書 18 行目に「今回削る対象は 2 段目の `use_default_work_pattern` 判定と、それに紐づく `SKIP` ログ ( `reason=use_default_work_pattern_false` ) だよ。」って書いてあるから、これも設計書どおり。
- でも、削除後のコードがどうなるかっていう「After」のコード例があったほうが、実装担当者は迷わないと思うw

#### 指摘5: 削除後のコード構造を明示する

設計書の「削除後の条件 ( `normal_day` のみ )」セクションに、削除後の条件は書いてあるけど、実際のコード構造が見えないと実装者が迷うかも。

提案としては、こんな感じの疑似コードを追加するといいんじゃないかな。

```python
# Before
if day_pattern != "normal_day":
    print(...reason=day_pattern_not_normal_day...)
    return "skipped"

if use_default_work_pattern is not True:
    print(...reason=use_default_work_pattern_false...)
    return "skipped"

decision = _decide_paid_holiday(...)
# ... (以下省略)

# After
if day_pattern != "normal_day":
    print(...reason=day_pattern_not_normal_day...)
    return "skipped"

decision = _decide_paid_holiday(...)
# ... (以下省略)
```

これがあると、実装担当者は「あ、 `use_default_work_pattern` の判定ブロック全体を削除すればいいんだな」ってすぐわかるよね♡

#### 指摘6: 変数 `use_default_work_pattern` の読み取りも削除する

設計書 22 行目に「`use_default_work_pattern` の読み取り自体を削除する。」って書いてあるから、これも設計に含まれてるね。

でも、コード上は `app/actions/bulk_attendance.py:244-246` で以下のように取得してるから、この 2 行も削除対象だよね。

```python
use_default_work_pattern = (
    body.get("use_default_work_pattern") if isinstance(body, dict) else None
)
```

この部分も削除されることを設計書に明記したほうがいいと思う。

#### 指摘7: 影響範囲の確認が丁寧

- grep で `use_default_work_pattern` を検索したら、実装ファイルとテストファイル以外には、過去の設計書や git ログにしか出てこなかった。
- 設計書 27-28 行目に「`grep` で見た限り、`use_default_work_pattern` を直接参照してるのはここだけで、他モジュールには波及しない。」って書いてあるのは正しいよ。
- この影響範囲の確認は LGTM だね♡

#### まとめ

設計の方向性は正しいし、影響範囲の調査も丁寧で良いと思う！

でも、以下の点を追加してくれると、実装担当者がもっとスムーズに作業できるよ。

- テストケースの追加観点をもっと具体的に (テストケース名とか、どこに追加するかとか)
- 削除後のコード構造を Before/After で明示する
- 変数 `use_default_work_pattern` の読み取り (244-246行目) も削除対象として明記する

これらを追加したら、あたしは LGTM 出すよ♡
