"""Loki(Grafana) ERROR/WARN 로그 트리아지.

모듈 구성
  cli.py            실행 순서 조율 (진입점)
  config.py         환경변수 설정, Loki 쿼리 조립
  grafana.py        Grafana /api/ds/query 조회
  parsing.py        로그 파싱, stack trace 분석, 템플릿화
  masking.py        민감정보 마스킹
  classifier.py     rules.yaml 분류, fingerprint
  aggregate.py      fingerprint 별 집계, 신규·급증 판정
  state.py          SQLite 상태 저장소
  issues.py         GitHub 이슈 생성·갱신·AI 라벨
  github_client.py  GitHub API 클라이언트
  discord.py        Discord 요약 알림
  models.py         공용 데이터 구조
  utils.py          시간 포맷
"""