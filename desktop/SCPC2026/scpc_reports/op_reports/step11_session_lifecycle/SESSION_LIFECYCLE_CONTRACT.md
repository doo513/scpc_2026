# Step 11 Session Lifecycle Contract

- committed state와 speculative overlay를 분리하고 overlay는 frozen JSON 값과 explicit provenance만 저장한다.
- dependency는 provisional read가 실제 producer write를 참조할 때만 생성한다.
- producer rollback은 read dependency consumer에만 cascade하며 독립 write를 자동 rollback하지 않는다.
- 독립 성공·실패가 섞이면 부분 commit 공식 근거가 없으므로 persistent commit을 보류하고 ASSUMPTION-PARTIAL-COMMIT-001을 남긴다.
- validation artifact lineage와 rollback-plan validation이 통과한 전체 unit만 atomic store에 commit한다.
- rollback된 decision에 semantic terminal이 남으면 plan을 후처리하지 않고 release를 거부한다.
- commit failure는 성공 answer로 승격할 수 없으며 persistent snapshot은 그대로 유지된다.
- Step 11 경로는 shadow-only다. legacy production의 validation-before-commit 문제는 아직 해결되지 않았다.
