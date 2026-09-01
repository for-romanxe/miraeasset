# 검수용 리포트 공유 폴더

`batch_check.py` 실행 결과 리포트(md)를 여기에 올려 팀이 함께 검수한다.

실행자는 리포트를 이 폴더로 복사해 커밋한다. 예:

```bash
cp eval/manual_qa/시험질문-승빈-안전경계-300-리포트.md eval/manual_qa/reports/
git add eval/manual_qa/reports/ && git commit -m "승빈 안전경계-300 리포트 (210문항까지)" && git push
```

검수자는 `git pull` 후 자기 담당 구간의 🔴를 열어 ①진짜 결함 ②판정 문제 ③애매 로 분류하고, 진짜 결함만 이슈 #66에 취합한다.

주의: 리포트에는 답변 전문이 들어가므로 비공개 레포 전용. 검수가 끝나면 이 폴더는 정리해도 된다.
