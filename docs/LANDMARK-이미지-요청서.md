# 전국 지도 랜드마크 이미지 17종 — 생성 요청서

> 이미지를 받으면 `frontend/public/landmarks/` 폴더에 **아래 파일명 그대로** 넣어주세요.
> 파일명은 법정동 시·도 코드입니다. 이름이 다르면 지도가 못 찾습니다.

## 1. 필요한 17종

| # | 파일명 | 시·도 | 랜드마크 | 영문 프롬프트용 표기 |
|---|---|---|---|---|
| 1 | `11.png` | 서울 | 남산서울타워 | N Seoul Tower (Namsan Tower) on a green hill |
| 2 | `26.png` | 부산 | 광안대교 | Gwangan Bridge (suspension bridge) over the sea at dusk |
| 3 | `27.png` | 대구 | 팔공산 갓바위 | Gatbawi stone Buddha statue on Palgongsan mountain |
| 4 | `28.png` | 인천 | 인천대교 | Incheon Bridge (cable-stayed bridge) over the sea |
| 5 | `29.png` | 광주 | 무등산 주상절리 | Mudeungsan mountain with columnar joint rock pillars |
| 6 | `30.png` | 대전 | 한빛탑 | Hanbit Tower, Daejeon Expo observation tower |
| 7 | `31.png` | 울산 | 대왕암 | Daewangam rocky coast with a white lighthouse |
| 8 | `36.png` | 세종 | 정부세종청사 | Government Complex Sejong, long building with wavy rooftop garden |
| 9 | `41.png` | 경기 | 수원화성 | Suwon Hwaseong Fortress gate with hanok-style pavilion |
| 10 | `43.png` | 충북 | 법주사 팔상전 | Palsangjeon, five-story wooden pagoda at Beopjusa temple |
| 11 | `44.png` | 충남 | 공주 공산성 | Gongsanseong fortress wall on a green hill, Gongju |
| 12 | `46.png` | 전남 | 여수 오동도 | Odongdo island with camellia flowers and a lighthouse, Yeosu |
| 13 | `47.png` | 경북 | 경주 첨성대 | Cheomseongdae, ancient stone observatory in Gyeongju |
| 14 | `48.png` | 경남 | 통영 한려수도 | Hallyeosudo archipelago with small green islands and a ferry, Tongyeong |
| 15 | `50.png` | 제주 | 성산일출봉 | Seongsan Ilchulbong volcanic crater peak with sunrise |
| 16 | `51.png` | 강원 | 설악산 | Seoraksan mountain, sharp rocky peaks with snow |
| 17 | `52.png` | 전북 | 전주 한옥마을 | Jeonju Hanok Village, traditional Korean tiled-roof houses |

## 2. 이미지 사양 (중요)

| 항목 | 요구사항 | 이유 |
|---|---|---|
| 크기 | **정사각형**, 512×512 이상 | 지도에서 37px, 상세패널에서 112px로 축소 사용 |
| 배경 | **투명 PNG 권장 / 흰 배경도 OK** | 지도에 얹어야 함. 흰 배경이면 내가 원형으로 잘라 씀 |
| 구도 | 대상 **하나만 가운데**, 여백 넉넉히 | 축소하면 가장자리가 잘림 |
| 글자 | **절대 넣지 말 것** | 지역명은 지도가 따로 표시함. 그림 속 글자는 축소 시 뭉개짐 |
| 형식 | PNG | 투명 지원 |

## 3. 공통 스타일 프롬프트 (17번 반복해서 쓰세요)

아래 문장에서 `[랜드마크]` 자리에 위 표의 **영문 표기**를 넣어 요청하면 톤이 통일됩니다.

```
Flat vector illustration of [랜드마크].
Style: soft pastel palette (mint green, sky blue, soft pink, cream, sand),
clean rounded dark-teal outlines, minimal flat shading, cute and friendly
Korean travel app icon style.
Composition: single centered subject, generous margin, square 1:1 canvas,
plain white background (or transparent).
No text, no letters, no numbers, no watermark, no border frame.
```

한국어로 요청하실 경우:

```
[랜드마크]를 플랫 벡터 일러스트로 그려줘.
스타일: 파스텔 톤(민트 그린, 하늘색, 연분홍, 크림, 모래색), 짙은 청록색 둥근 외곽선,
그림자 최소화, 귀엽고 친근한 한국 여행 앱 아이콘 느낌.
구도: 대상 하나만 정중앙, 여백 넉넉히, 정사각형 1:1, 배경은 흰색(또는 투명).
글자·숫자·워터마크·테두리 프레임 넣지 말 것.
```

## 4. 받은 뒤 절차

1. `frontend/public/landmarks/` 에 `11.png` … `52.png` 로 저장
2. 오케스트레이터에게 알려주면 지도에 연결 + 화면 확인
3. **기존 SVG 그림은 폴백으로 남긴다** — 이미지가 없거나 로딩 실패해도 지도가 비지 않게

## 5. 미리 정해둘 것 (법률)

- 생성에 쓴 서비스의 **약관상 상업적 이용 가능 여부**를 확인해 둘 것(무료 플랜이 상업 이용을
  막는 곳이 있다).
- AI 생성물은 한국 저작권법상 **저작권 보호를 못 받을 수 있다** — 쓰는 데는 지장 없으나
  "우리 것"이라고 독점 주장하기는 어렵다. 공모전 제출물 설명에 굳이 밝힐 의무는 없으나,
  심사 측이 물으면 사실대로 답한다.
- 특정 실존 인물·상표·기업 로고가 그림에 들어가지 않도록 확인할 것.
