아이돌 작사 스치파이 Remix (세가새턴) 한글패치 v1.1

[이 판에 들어 있는 것]
  - 화면의 일본어 그림 글자 한글화 (타이틀 로고, 오프닝, 메뉴, 캐릭터 선택, 대국 화면,
    역 이름, 상대 소개 카드, 패널 매치, 클리어 화면, 엔딩 스태프 롤 등)
    「Remix」 로고는 원본 영문 그대로입니다.
  - 대사 음성 한국어 자막
      대국 전 대화, 캐릭터 소개, 패널 매치 장면·설명, 우승·후일담 등 음성 464개, 1,678줄.
      대사가 들리는 순간에 맞춰 화면 아래에 나옵니다.
      대국 중 짧은 호출(퐁·리치 등)에는 자막을 넣지 않았습니다.
  - 음성은 원어(일본어) 그대로입니다.

[자막 번역에 대해]
  원작에 대본이 없어 음성 인식으로 받아쓴 뒤 번역했습니다. 번역은 초벌, 2차 검수,
  최종 검수를 거쳤지만 음성을 사람 귀로 다시 듣고 맞춰 본 것은 아닙니다.
  잘 안 들리는 곳은 문맥으로 추정한 부분이 있습니다.

[들어 있는 파일]
  Redump\   ← 트랙별로 나뉜 BIN/CUE (Redump 판, BIN 6개)를 가진 분
    Idol Janshi Suchie-Pai Remix (Japan) (Track 1).bin.bps   ← 1번 트랙에 씌우는 패치
    Idol Janshi Suchie-Pai Remix (Korean).cue                 ← 한글판을 여는 파일
  CHD\      ← CHD 를 chdman 으로 푼 BIN 하나 + CUE 를 가진 분
    Idol Janshi Suchie-Pai Remix (Japan).bin.bps              ← BIN 하나에 씌우는 패치
    Idol Janshi Suchie-Pai Remix (Korean).cue                 ← 한글판을 여는 파일
  README.txt                                                  ← 이 안내

  두 패치는 같은 한글판을 만듭니다. 가진 원본에 맞는 폴더 하나만 쓰면 됩니다.
  패치가 원본을 검사하므로 판이 다르면 적용되지 않습니다.

[가) Redump 판 — BIN 6개]
  원본: Idol Janshi Suchie-Pai Remix (Japan) (Track 1).bin
        346,962,336바이트  SHA-1 ac800da596c31d478989e9dac309198ddf527143
        (Track 2)~(Track 6) 은 음악 트랙이라 고치지 않습니다.
  1. 원본 폴더를 통째로 복사해 둡니다(보관용).
  2. Floating IPS(flips)로 패치합니다. https://github.com/Alcaro/Flips/releases
       패치 = Redump\Idol Janshi Suchie-Pai Remix (Japan) (Track 1).bin.bps
       원본 = Idol Janshi Suchie-Pai Remix (Japan) (Track 1).bin
     저장할 이름은 반드시 아래처럼, 원본과 같은 폴더에 저장합니다.
       Idol Janshi Suchie-Pai Remix (Korean) (Track 1).bin
  3. Redump\Idol Janshi Suchie-Pai Remix (Korean).cue 를 같은 폴더에 넣습니다.
     (한글판 cue 는 한글판 Track 1 과 원본 Track 2~6 을 함께 읽습니다.)
  4. 에뮬레이터에서 Idol Janshi Suchie-Pai Remix (Korean).cue 를 엽니다.

[나) CHD — chdman 으로 푼 BIN 하나]
  원본 CHD 를 먼저 BIN/CUE 로 풉니다(MAME 에 들어 있는 chdman).
       chdman extractcd -i "원본.chd" -o "Idol Janshi Suchie-Pai Remix (Japan).cue"
  원본: 위에서 나온 BIN 하나 (480,885,216바이트)  SHA-1 5f94668ae120bd99a5d27178e538d05566e64220
        Redump 판 BIN 6개를 차례로 하나로 합친 BIN 도 이것과 같습니다.
  1. Floating IPS(flips)로 패치합니다.
       패치 = CHD\Idol Janshi Suchie-Pai Remix (Japan).bin.bps
       원본 = 위의 BIN
     저장할 이름: Idol Janshi Suchie-Pai Remix (Korean).bin
  2. CHD\Idol Janshi Suchie-Pai Remix (Korean).cue 를 같은 폴더에 넣고 에뮬레이터에서 엽니다.
     한글판 BIN 은 음악까지 다 들어 있어 원본 BIN 없이도 돌아갑니다.

[실행]
  Mednafen 에서 플레이해 확인했습니다. RetroArch 의 Beetle Saturn 코어 등 cue 를 여는
  새턴 에뮬레이터에서 쓰면 됩니다. CHD 로 묶어(chdman createcd) 써도 됩니다.
  세가새턴 BIOS 는 따로 준비해야 합니다.
  타이틀 화면에 한글 "아이돌작사 스치파이♡" 로고가 나오면 성공입니다.

[주의]
  원판은 18세 이상 이용가 성인용 게임입니다.
  이 패치는 원본 게임 데이터를 포함하지 않습니다. 원본 파일 요청은 받지 않습니다.
  원작의 권리는 쟈레코와 각 권리자에게 있습니다. 합법적으로 가진 원본에만 적용하세요.
