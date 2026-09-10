# Fantasy Basketball Value & Salary Engine

## Technical Reference / Development Specification

Bu doküman iki ana sistemi tek bir referansta birleştirir:

1. **Performance TOTAL Projection Engine**
2. **Auction Market Value + Free Agent Salary Engine**

Amaç; oyuncunun farklı maç sayısı senaryosundaki fantasy katkısını doğru şekilde yeniden hesaplamak, bunu tüm oyuncu havuzuna göre sıralamak ve ardından 12 takımlı, 13 oyunculu, takım başına **$210 salary cap** kullanılan bir lig ekonomisinde dolar değerine çevirmektir.

---

# 1. Core Principles

Sistem üç ayrı değeri kesin olarak ayırmalıdır:

```text
Performance TOTAL
↓
Auction Market Value
↓
Free Agent Salary
```

### Performance TOTAL
Oyuncunun 9-cat fantasy katkısının toplam değeridir.

### Auction Market Value
Oyuncunun $210 cap'li gerçek auction ortamındaki piyasa değeridir.

### Free Agent Salary
Draft edilmeyen ve FA üzerinden alınan oyuncuya uygulanacak kontrat maaşıdır.

Bu üç değer birbirine eşit olmak zorunda değildir.

---

# 2. League Configuration

Default league setup:

```ts
const leagueConfig = {
  teams: 12,
  rosterSize: 13,
  salaryCapPerTeam: 210,
  minimumSalary: 1,
  maxFASalary: 15
}
```

Toplam drafted player:

\[
12 \times 13 = 156
\]

Toplam league budget:

\[
12 \times 210 = 2520
\]

Minimum salary budget:

\[
156 \times 1 = 156
\]

Premium olarak dağıtılabilecek toplam bütçe:

\[
2520 - 156 = 2364
\]

---

# 3. Player Data Model

Minimum player schema:

```ts
type Player = {
  rank: number
  name: string
  pos?: string
  team?: string

  gp: number
  minutes: number

  fgPct: number
  fgm: number
  fga: number

  ftPct: number
  ftm: number
  fta: number

  threePM: number
  pts: number
  reb: number
  ast: number
  stl: number
  blk: number
  tov: number

  total: number
}
```

Kaynak `R#` alanında rank değişim değeri de bulunuyorsa ayrı parse edilmelidir.

Örnek:

```text
346 1
```

ise:

```ts
rank = 346
rankChange = 1
```

---

# 4. Games Played Projection

Bir oyuncunun farklı maç sayısındaki değerini hesaplamak için TOTAL doğrudan ölçeklenmemelidir.

## Yanlış yöntem

\[
ProjectedTOTAL =
OriginalTOTAL \times \frac{TargetGP}{CurrentGP}
\]

Bu yaklaşım kullanılmamalıdır.

---

## Doğru yöntem

Önce scaling factor:

\[
ScaleFactor =
\frac{TargetGP}{CurrentGP}
\]

Daha sonra volume/counting stats ölçeklenir:

\[
FGM^* = FGM \times ScaleFactor
\]

\[
FGA^* = FGA \times ScaleFactor
\]

\[
FTM^* = FTM \times ScaleFactor
\]

\[
FTA^* = FTA \times ScaleFactor
\]

\[
3PM^* = 3PM \times ScaleFactor
\]

\[
PTS^* = PTS \times ScaleFactor
\]

\[
REB^* = REB \times ScaleFactor
\]

\[
AST^* = AST \times ScaleFactor
\]

\[
STL^* = STL \times ScaleFactor
\]

\[
BLK^* = BLK \times ScaleFactor
\]

\[
TO^* = TO \times ScaleFactor
\]

\[
MIN^* = MIN \times ScaleFactor
\]

Yüzdeler yeniden türetilir:

\[
FG\%^* = \frac{FGM^*}{FGA^*}
\]

\[
FT\%^* = \frac{FTM^*}{FTA^*}
\]

Lineer scaling nedeniyle yüzdeler aynı kalacaktır.

> Ara hesaplamalarda rounding yapılmamalıdır.

---

# 5. Percentage Volume Impact

FG% ve FT% yalnızca yüzde değeri olarak değerlendirilmemelidir.

Örnek:

```text
48.4% on 3 attempts
```

ile:

```text
48.4% on 13 attempts
```

aynı fantasy katkısına sahip değildir.

Bu yüzden volume-weighted percentage impact kullanılmalıdır.

---

## League Reference Percentages

\[
LeagueFG =
\frac{\sum FGM}{\sum FGA}
\]

\[
LeagueFT =
\frac{\sum FTM}{\sum FTA}
\]

Bu değerler calibration dataset'ten bir kez hesaplanır.

What-if projection sırasında target player değiştiğinde yeniden hesaplanmaz.

---

## FG Impact

\[
FGImpact_i =
FGM_i - FGA_i \times LeagueFG
\]

Eşdeğer:

\[
FGImpact_i =
FGA_i \times (FG\%_i - LeagueFG)
\]

---

## FT Impact

\[
FTImpact_i =
FTM_i - FTA_i \times LeagueFT
\]

Eşdeğer:

\[
FTImpact_i =
FTA_i \times (FT\%_i - LeagueFT)
\]

---

# 6. Category Feature Vector

Her oyuncu şu 9 kategorili vector ile temsil edilir:

\[
X_i =
[
FGImpact,
FTImpact,
3PM,
PTS,
REB,
AST,
STL,
BLK,
TO
]
\]

İlk 8 kategoride yüksek değer iyidir.

Turnover kategorisinde düşük değer iyidir.

---

# 7. Category Value Function

Her kategori için affine scoring function:

\[
RawCategoryValue_{i,c}
=
a_c + b_c X_{i,c}
\]

H2H negative floor:

\[
CategoryValue_{i,c}
=
\max(-2,\ a_c + b_c X_{i,c})
\]

Pozitif kategoriler:

\[
b_c \ge 0
\]

Turnover:

\[
b_{TO} \le 0
\]

Kategori ağırlığı varsa:

\[
WeightedCategoryValue_{i,c}
=
w_c \times CategoryValue_{i,c}
\]

Default:

```ts
const categoryWeights = {
  FG: 1,
  FT: 1,
  THREE_PM: 1,
  PTS: 1,
  REB: 1,
  AST: 1,
  STL: 1,
  BLK: 1,
  TO: 1
}
```

---

# 8. TOTAL Formula

Oyuncunun TOTAL değeri:

\[
TOTAL_i =
\sum_c WeightedCategoryValue_{i,c}
\]

Açık hali:

\[
TOTAL_i =
w_{FG}\max(-2,a_{FG}+b_{FG}FGImpact_i)
\]

\[
+
w_{FT}\max(-2,a_{FT}+b_{FT}FTImpact_i)
\]

\[
+
w_{3PM}\max(-2,a_{3PM}+b_{3PM}3PM_i)
\]

\[
+
w_{PTS}\max(-2,a_{PTS}+b_{PTS}PTS_i)
\]

\[
+
w_{REB}\max(-2,a_{REB}+b_{REB}REB_i)
\]

\[
+
w_{AST}\max(-2,a_{AST}+b_{AST}AST_i)
\]

\[
+
w_{STL}\max(-2,a_{STL}+b_{STL}STL_i)
\]

\[
+
w_{BLK}\max(-2,a_{BLK}+b_{BLK}BLK_i)
\]

\[
+
w_{TO}\max(-2,a_{TO}+b_{TO}TO_i)
\]

---

# 9. Calibration Engine

`a_c` ve `b_c` katsayıları hard-code edilmemelidir.

Kaynak dataset'teki gerçek TOTAL değerleri üzerinden reverse calibration yapılmalıdır.

Parametre seti:

\[
\theta =
\{
a_{FG},b_{FG},
a_{FT},b_{FT},
a_{3PM},b_{3PM},
a_{PTS},b_{PTS},
a_{REB},b_{REB},
a_{AST},b_{AST},
a_{STL},b_{STL},
a_{BLK},b_{BLK},
a_{TO},b_{TO}
\}
\]

Observed TOTAL:

\[
ObservedTOTAL_i
\]

Predicted TOTAL:

\[
PredictedTOTAL_i(\theta)
\]

Optimization:

\[
\min_{\theta}
\sum_i
(
PredictedTOTAL_i(\theta)
-
ObservedTOTAL_i
)^2
\]

Constraints:

\[
b_{FG},b_{FT},b_{3PM},b_{PTS},b_{REB},b_{AST},b_{STL},b_{BLK} \ge 0
\]

\[
b_{TO} \le 0
\]

Recommended implementation:

```python
scipy.optimize.least_squares
```

veya eşdeğer constrained nonlinear optimizer.

---

# 10. Calibration Initialization

Pozitif kategoriler için:

\[
b^0_c =
\frac{1}{SD(X_c)}
\]

\[
a^0_c =
-\frac{MEAN(X_c)}{SD(X_c)}
\]

Turnover:

\[
b^0_{TO} =
-\frac{1}{SD(TO)}
\]

\[
a^0_{TO} =
\frac{MEAN(TO)}{SD(TO)}
\]

Opsiyonel regularization:

\[
Loss =
SSE +
\lambda ||\theta-\theta_0||^2
\]

Default:

\[
\lambda = 10^{-6}
\]

---

# 11. Calibration Validation

Her oyuncu için:

\[
Error_i =
PredictedTOTAL_i - ObservedTOTAL_i
\]

MAE:

\[
MAE =
mean(|Error_i|)
\]

RMSE:

\[
RMSE =
\sqrt{mean(Error_i^2)}
\]

MAX ERROR:

\[
MAXERROR =
\max(|Error_i|)
\]

Target:

```text
MAE < 0.01
```

Kalibrasyon çok daha kötü sonuç veriyorsa sistem warning üretmelidir.

---

# 12. What-if Projection Flow

```text
1. Target player'ı bul
2. currentGP oku
3. scaleFactor = targetGP / currentGP
4. Raw stats'leri scale et
5. FGImpact yeniden hesapla
6. FTImpact yeniden hesapla
7. Category scores hesapla
8. -2 floor uygula
9. Category weights uygula
10. TOTAL üret
11. Tüm player pool içinde yeniden rank et
```

Calibration coefficients projection sırasında yeniden fit edilmemelidir.

---

# 13. Re-ranking

Target dışındaki oyuncular için mevcut TOTAL kullanılabilir.

Target player:

```text
projectedTotal
```

ile değerlendirilir.

Yeni rank:

\[
NewRank =
1 +
Count(OtherPlayerTOTAL > ProjectedTOTAL)
\]

Tie durumunda competition rank:

```text
rank = 1 + strictlyGreaterCount
```

---

# 14. Dejounte Murray Regression Test

Reference input:

```text
Player: Dejounte Murray
GP: 14

FGM: 88
FGA: 182

FTM: 39
FTA: 45

3PM: 19
PTS: 234
REB: 75
AST: 89
STL: 23
BLK: 3
TO: 47

Observed TOTAL: 5.15
Observed Rank: 346
```

Target:

```text
Target GP: 64
```

Scale factor:

\[
\frac{64}{14}
=
4.5714285714
\]

Projected raw stats:

```text
FGM ≈ 402.2857
FGA = 832.0000

FTM ≈ 178.2857
FTA ≈ 205.7143

3PM ≈ 86.8571
PTS ≈ 1069.7143
REB ≈ 342.8571
AST ≈ 406.8571
STL ≈ 105.1429
BLK ≈ 13.7143
TO ≈ 214.8571
```

Expected:

```text
Projected TOTAL ≈ 16.98
Projected Rank ≈ 42
```

Tolerance:

```text
TOTAL tolerance: ±0.05
```

---

# 15. Auction Economy

Drafted player count:

\[
N = 156
\]

Replacement player:

\[
ReplacementRank = 157
\]

Reference replacement TOTAL:

\[
ReplacementTOTAL \approx 10.80
\]

Her oyuncunun replacement üstü değeri:

\[
Surplus_i =
\max(0,\ TOTAL_i - ReplacementTOTAL)
\]

---

# 16. Real Auction Market Premium

Gerçek auction draftlarda para elit oyunculara kayar.

Bu yüzden düz lineer salary dağılımı kullanılmamalıdır.

Default market multipliers:

```ts
function getMarketWeight(rank: number): number {
  if (rank <= 3) return 1.25
  if (rank <= 12) return 1.15
  if (rank <= 24) return 1.08
  if (rank <= 48) return 1.00
  if (rank <= 84) return 0.95
  if (rank <= 120) return 0.85
  if (rank <= 144) return 0.70

  return 0
}
```

---

# 17. Final Round Rule

Round 13:

```text
Ranks 145–156
```

tüm oyuncular:

\[
Salary = \$1
\]

Hard rule:

```ts
if (rank >= 145 && rank <= 156) {
  salary = 1
}
```

Bu kural yalnızca Auction Market Value katmanına uygulanır.

Underlying TOTAL değiştirilmez.

---

# 18. Market Score

İlk 144 oyuncu:

\[
MarketScore_i =
Surplus_i \times MarketWeight_i
\]

Açık hali:

\[
MarketScore_i =
\max(0,TOTAL_i-ReplacementTOTAL)
\times
MarketWeight(rank_i)
\]

---

# 19. Budget Normalization

League Budget:

\[
LeagueBudget = 2520
\]

Minimum Salary Reserve:

\[
MinimumBudget = 156
\]

Premium Pool:

\[
PremiumBudget =
2520 - 156
=
2364
\]

Dollar per Market Score:

\[
DollarPerMarketScore =
\frac{PremiumBudget}
{\sum_{i=1}^{144}MarketScore_i}
\]

Auction salary:

\[
AuctionMarketValue_i =
1 +
MarketScore_i
\times
DollarPerMarketScore
\]

Ranks 145–156:

\[
AuctionMarketValue_i = 1
\]

Validation:

\[
\sum_{i=1}^{156}
AuctionMarketValue_i
=
2520
\]

---

# 20. Expected Auction Curve

Reference shape:

| Round | Rank | Expected Avg |
|---|---:|---:|
| 1 | 1–12 | ~$55–56 |
| 2 | 13–24 | ~$34 |
| 3 | 25–36 | ~$26 |
| 4 | 37–48 | ~$21–22 |
| 5 | 49–60 | ~$17–18 |
| 6 | 61–72 | ~$14 |
| 7 | 73–84 | ~$12 |
| 8 | 85–96 | ~$9 |
| 9 | 97–108 | ~$7–8 |
| 10 | 109–120 | ~$5 |
| 11 | 121–132 | ~$3–4 |
| 12 | 133–144 | ~$2–3 |
| 13 | 145–156 | $1 |

Bu değerler hard-coded player salary değildir.

Bunlar sanity-check değerleridir.

---

# 21. Elite Player Sanity Check

Reference:

```text
Nikola Jokic
Rank: 1
TOTAL ≈ 29.91
```

Expected auction value:

```text
≈ $75–80
```

Target:

```text
≈ $79
```

Acceptance:

```text
$75 <= Salary <= $82
```

Eğer model Rank #1 oyuncuya ~$64 veriyorsa star premium yeterli değildir.

---

# 22. Round Weight Logic

Ekonomik curve:

```text
Elite stars = heavy premium

Round 1 = very expensive

Round 2 = elevated premium

Rounds 3–6 = normalization

Rounds 7–10 = value zone

Rounds 11–12 = cheap depth

Round 13 = exactly $1
```

---

# 23. Free Agent Salary System

FA oyuncusuna tam Auction Market Value verilmez.

Aynı zamanda bütün FA oyuncuları $1 da kalmamalıdır.

Default:

\[
FASalary =
\min(
15,
1 + 0.30(AuctionMarketValue - 1)
)
\]

Implementation:

```ts
function calculateFASalary(marketValue: number) {
  return Math.min(
    15,
    1 + 0.30 * Math.max(0, marketValue - 1)
  )
}
```

---

# 24. FA Hard Cap

Maximum FA Salary:

\[
\boxed{\$15}
\]

Hard rule:

```ts
MAX_FA_SALARY = 15
```

Hiçbir FA kontratı:

\[
FASalary > 15
\]

olamaz.

---

# 25. FA Salary Examples

Formula:

\[
FASalary =
\min(
15,
1 + 0.30(MarketValue-1)
)
\]

| Auction Market Value | FA Salary |
|---:|---:|
| $1 | $1.00 |
| $3 | $1.60 |
| $5 | $2.20 |
| $10 | $3.70 |
| $15 | $5.20 |
| $20 | $6.70 |
| $25 | $8.20 |
| $30 | $9.70 |
| $35 | $11.20 |
| $40 | $12.70 |
| $45 | $14.20 |
| $48 | $15.00 |
| $50 | $15.00 |
| $60 | $15.00 |
| $80 | $15.00 |

FA cap'e ulaşılan yaklaşık Market Value:

\[
1 + 0.30(MV-1) = 15
\]

\[
MV \approx 47.67
\]

Yani:

\[
MarketValue \ge 47.67
\Rightarrow
FASalary = 15
\]

---

# 26. FA Surplus

FA pickup'ın sağladığı ekonomik avantaj:

\[
FASurplus =
AuctionMarketValue - FASalary
\]

Amaç:

```text
Good FA pickup = rewarded

Elite FA pickup = strongly rewarded

League-breaking $1 breakout contracts = prevented
```

---

# 27. Nickeil Alexander-Walker Example

Reference projection:

```text
Target GP: 65
Projected TOTAL ≈ 17.97
Projected Rank ≈ 34
```

Auction Market Value:

```text
≈ $24–25
```

Örnek:

\[
MarketValue = 24.42
\]

FA Salary:

\[
1 + 0.30(24.42-1)
\]

\[
= 1 + 7.026
\]

\[
= 8.026
\]

Sonuç:

```text
Performance TOTAL: 17.97
Projected Rank: ~34
Auction Market Value: ~$24.42
FA Salary: ~$8.03
FA Salary Display: $8
```

---

# 28. Elite FA Example

Bir oyuncunun Auction Market Value'su:

\[
60
\]

olsun.

Raw FA formula:

\[
1 + 0.30(60-1)
=
18.70
\]

Ama hard cap:

\[
FASalary =
\min(15,18.70)
=
15
\]

Sonuç:

```text
Market Value = $60
FA Salary = $15
FA Surplus = $45
```

---

# 29. Rounding Rules

Internal:

```text
full floating-point precision
```

Database:

```ts
{
  totalRaw: number,
  marketValueRaw: number,
  faSalaryRaw: number
}
```

UI:

```text
Auction Market Value → nearest whole dollar
FA Salary → nearest whole dollar
```

Örnek:

```text
24.42 → $24
79.10 → $79
8.03 → $8
11.20 → $11
```

Raw değerler database'de saklanmalıdır.

---

# 30. API Design

## Projection Endpoint

```http
POST /api/player-value/project
```

Request:

```json
{
  "playerId": "nickeil-alexander-walker",
  "targetGames": 65
}
```

Response:

```json
{
  "player": "Nickeil Alexander-Walker",

  "projection": {
    "games": 65,
    "total": 17.97,
    "rank": 34
  },

  "economics": {
    "auctionMarketValue": 24.42,
    "auctionMarketValueRounded": 24,

    "faSalary": 8.03,
    "faSalaryRounded": 8,

    "faSalaryCap": 15,

    "marketSurplusIfFA": 16.39
  }
}
```

---

# 31. Recommended Architecture

```text
Dataset Parser
↓
Dataset Normalizer
↓
Calibration Engine
↓
Performance Scoring Engine
↓
Games Played Projection Engine
↓
Ranking Engine
↓
Auction Economy Engine
↓
Free Agent Salary Engine
↓
Explanation Engine
↓
API / UI
```

---

# 32. Module Responsibilities

## Dataset Parser
CSV / Markdown / DB verisini parse eder.

## Dataset Normalizer
FG/FT made-attempted alanlarını normalize eder.

## Calibration Engine
Kaynak TOTAL'lardan scoring katsayılarını fit eder.

## Performance Scoring Engine
Kategori contribution ve TOTAL hesaplar.

## Projection Engine
What-if GP senaryosu oluşturur.

## Ranking Engine
Yeni TOTAL'a göre rank belirler.

## Auction Economy Engine
TOTAL + rank → market value üretir.

## FA Salary Engine
Market value → discounted FA salary üretir.

## Explanation Engine
Kullanıcıya matematiksel açıklama üretir.

---

# 33. Economy Config

```ts
const economyConfig = {
  teams: 12,
  rosterSize: 13,
  salaryCapPerTeam: 210,
  minimumSalary: 1,

  replacementRank: 157,

  marketWeights: [
    { from: 1, to: 3, multiplier: 1.25 },
    { from: 4, to: 12, multiplier: 1.15 },
    { from: 13, to: 24, multiplier: 1.08 },
    { from: 25, to: 48, multiplier: 1.00 },
    { from: 49, to: 84, multiplier: 0.95 },
    { from: 85, to: 120, multiplier: 0.85 },
    { from: 121, to: 144, multiplier: 0.70 }
  ],

  finalRound: {
    fromRank: 145,
    toRank: 156,
    salary: 1
  },

  freeAgency: {
    valueFactor: 0.30,
    minimumSalary: 1,
    maximumSalary: 15
  }
}
```

---

# 34. Deterministic Rule

Aynı input her zaman aynı output'u üretmelidir.

```text
same dataset
+
same calibration
+
same economy config
+
same player
+
same target GP
=
same TOTAL
+
same rank
+
same auction market value
+
same FA salary
```

---

# 35. Business Rules

Aşağıdaki kurallar zorunludur:

```text
1. TOTAL doğrudan GP ile çarpılmaz.

2. Raw stats target GP'ye ölçeklenir.

3. FG% ve FT% volume weighted hesaplanır.

4. Category scores calibration üzerinden üretilir.

5. H2H negative floor = -2.

6. Projected player tüm havuzda yeniden rank edilir.

7. Replacement rank = 157.

8. Drafted player count = 156.

9. Team cap = $210.

10. League budget = $2520.

11. Round 1 ve Round 2 market premium alır.

12. Round 13 ranks 145–156 = exactly $1.

13. Top player yaklaşık $75–80 bandına çıkabilmelidir.

14. Auction Market Value ve FA Salary farklı field'lardır.

15. FA salary formula market value'nun %30'una dayanır.

16. Minimum FA Salary = $1.

17. Maximum FA Salary = exactly $15.

18. Hiçbir FA salary $15'i geçemez.

19. FA pickup ekonomik surplus yaratmalıdır.

20. Bütün hesaplar internal full precision ile yapılmalıdır.
```

---

# 36. Future Extensions

Sistem ileride şu özelliklere açık olmalıdır:

```text
Custom category weights
Punt categories
8-cat
9-cat
H2H
Standard
Minus-1
Custom GP
Custom MPG
Custom stat overrides
Injury scenarios
Rest-of-season projection
Multi-player what-if
Auction inflation
Live auction remaining budget
Positional scarcity
Keeper salary
Contract escalation
FA renewal rules
Replacement-by-position
VORP-style scoring
Auction nomination strategy
```

---

# 37. Priority Implementation Order

```text
1. Dataset Parser
2. Dataset Normalizer
3. Calibration Engine
4. TOTAL Validation
5. Games Played Projection
6. Re-ranking
7. Auction Market Value
8. Budget Normalization
9. Star Premium
10. Round 13 $1 rule
11. FA Salary
12. $15 FA hard cap
13. Regression tests
14. API
15. UI explanation
```

---

# 38. Required Regression Tests

## Test A — Original TOTAL reproduction

Calibration engine kaynak TOTAL değerlerini yüksek doğrulukta yeniden üretebilmelidir.

Target:

```text
MAE < 0.01
```

---

## Test B — Dejounte Murray 64 GP

Expected:

```text
TOTAL ≈ 16.98
Rank ≈ 42
```

---

## Test C — Jokic Market Value

Expected:

```text
Rank 1
Auction Market Value ≈ $75–80
Reference ≈ $79
```

---

## Test D — Final Round

```text
Ranks 145–156
```

Expected:

```text
Every player = $1
```

---

## Test E — League Budget Conservation

\[
\sum_{i=1}^{156}
AuctionMarketValue_i
=
2520
\]

---

## Test F — FA Hard Cap

Input:

```text
Market Value = $80
```

Expected:

```text
FA Salary = $15
```

---

## Test G — Nickeil Alexander-Walker

Reference:

```text
Target GP = 65
Projected TOTAL ≈ 17.97
Projected Rank ≈ 34
Auction Market Value ≈ $24–25
FA Salary ≈ $8
```

---

# 39. Final Formula Summary

## GP Scaling

\[
ScaleFactor =
\frac{TargetGP}{CurrentGP}
\]

\[
ProjectedStat =
OriginalStat \times ScaleFactor
\]

---

## Percentage Impact

\[
FGImpact =
FGM - FGA \times LeagueFG
\]

\[
FTImpact =
FTM - FTA \times LeagueFT
\]

---

## Category Score

\[
CategoryValue =
\max(-2,\ a+bX)
\]

---

## Performance TOTAL

\[
TOTAL =
\sum_c w_c CategoryValue_c
\]

---

## Re-ranking

\[
Rank =
1 +
Count(PlayerTOTAL > TargetTOTAL)
\]

---

## Replacement Surplus

\[
Surplus =
\max(0,TOTAL-ReplacementTOTAL)
\]

---

## Market Score

\[
MarketScore =
Surplus \times MarketWeight
\]

---

## Auction Conversion Factor

\[
DollarPerMarketScore =
\frac{2364}
{\sum MarketScore_{1..144}}
\]

---

## Auction Market Value

\[
AuctionMarketValue =
1 +
MarketScore
\times
DollarPerMarketScore
\]

Exception:

\[
Rank \in [145,156]
\Rightarrow
AuctionMarketValue = 1
\]

---

## FA Salary

\[
FASalary =
\min(
15,
1 + 0.30(AuctionMarketValue-1)
)
\]

---

## FA Surplus

\[
FASurplus =
AuctionMarketValue-FASalary
\]

---

# 40. Final System Goal

Sistem şu davranışı üretmelidir:

```text
Performance → mathematically recalculated

Rank → player pool relative

Auction price → budget normalized

Stars → premium priced

Round 1 → expensive

Round 2 → premium

Middle rounds → progressively cheaper

Final round → $1

Free agents → discounted contracts

Elite free agents → capped at $15

League budget → always conserved
```

Bu dosya uygulamanın ana matematik ve business-rule referansı olarak kullanılmalıdır.
