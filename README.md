# 라벨링 없는 P&ID 도면 태그의 추출 자동화 및 자기지도 OCR

[문제 정의]
기존 조선소 도면 해석 업무 프로세스는 다음과 같습니다.
[스캔 도면 → 엔지니어가 육안 판독 → 태그 수기 입력 → 검토자 재확인 → DB 등록]
사람이 수기로 입력하며 오독이 발생할 시 재작업, 조선소마다 태그 체계가 달라 담당자 교체 시 학습 비용이 발생합니다.

[이렇게 해결합니다]
'청사진'은 Neuro-symbolic 기반 P&ID 태그 디코딩 프레임워크입니다. 
계층적 문법(ISA-5.1 표준 → Vendor → Project → Drawing)을 OCR 결과에 적용합니다(Colab OCR 코드를 통해 산출한 csv 파일을 입력 받음).
Never-Fabricate 방식으로 근거 없는 자동 수정을 방지합니다. 런타임은 CPU 전용이며, Python 표준 라이브러리만 사용합니다.
이 패키지는 OCR 수행이나 문법 학습(Grammar Induction) 을 포함하지 않습니다. OCR 검출은 Colab OCR 코드 단계에서 수행되어 Cache CSV를 생성하며, 문법은 오프라인에서 학습되어 CSV 사전 형태로 저장됩니다. 
본 패키지는 해당 사전을 읽어 ​새로운 P&ID 도면에 적용하여 일반화 성능을 평가하는 것이 목적입니다.

---

## 계층적 문법(Hierarchical Grammar)을 사용하는 이유

순수 데이터 기반 문법은 학습에 포함되지 않은 Vendor에서는 일반화 성능이 크게 저하됩니다. 
실제 Holdout 실험에서도 새로운 조선소(Vendor)에서는 약 30% 수준의 성능만 나타났습니다. 이는 Vendor마다 태그 명명 규칙이 다르기 때문입니다.

실제 산업 P&ID는 국제 표준을 기반으로 작성되므로, '청사진'은 데이터 기반 문법 위에 표준 지식을 계층적으로 결합하는 방식을 적용했습니다.

```
L1  국제 표준 사전               ISA-5.1-2024 / ISO 10628 / IEC 62424   (soft prior)
L2  Vendor tag grammar        Vendor별 오프라인 학습                    (data/grammar/)
L3  Project emergent grammar  여러 Vendor에서 공통적으로 학습된 규칙        (data/grammar/)
L4  Drawing repetition        동일 도면 내 Self-supervision            (runtime)
```

적용 우선순위는 다음과 같습니다: exact vocab (L4/L3/L2) → slot repair → ISA prior (L1) → **reject**.
ISA 표준은 Hard Rule이 아닌 Soft Prior로만 사용됩니다 : 기업 고유 약어, 프로젝트별 명명 규칙, OCR이 그대로 유지해야 하는 문자열 등이 존재하기 때문입니다.
어느 계층에서도 충분한 신뢰도로 복원되지 않는 경우에는 원본 OCR 문자열을 그대로 유지하고 **사람이 검토**하도록 전달합니다.
즉, 가짜 태그를 생성하여 재작업을 방지하는 것이 '청사진' 시스템의 가장 중요한 원칙입니다.

---

## Install

```bash
pip install -e .          # editable, for development in VS Code
```

No GPU, no heavy deps. `data/isa_5_1.json` (ISA-5.1-2024 Table 4) and
`data/grammar/*.csv` ship with the package.

---

## 사용 방법

### 새로운 P&ID 도면 검증 (generalization test)

```bash
python -m pid_tag_ocr.validate --cache path/to/new_drawing.csv
# optional ground truth for full accuracy metrics:
python -m pid_tag_ocr.validate --cache new.csv --gold gold.csv --vendor V03 --out result.json
```

Cache CSV schema (from the detection stage): `x,y,w,h,rot,conf,raw`
Gold CSV schema (optional): `raw,gold`

### As a library

```python
from pid_tag_ocr import HierarchicalGrammar, classify

G = HierarchicalGrammar()
G.decode("MKIWWM-841679").decoded   # -> "MK9WWM-841679"  (cross-mask repair)
G.decode("LL").decoded              # -> "LI"             (ISA snap)
G.decode("NOTE1").confident         # -> False            (flagged, not invented)
classify("12\"-VA-MQIEX-510275").type   # -> "line_number"
```

---

## Grammar Dictionary 재생성

새로운 OCR Cache가 추가되면 오프라인에서 Grammar를 다시 생성할 수 있습니다 :

```bash
python build_grammar.py --cache path/to/cache_dir --out data/grammar
```

OCR에서는
'9 → I', '0 → O', '8 → B' 처럼 숫자가 문자로 오인식되는 경우가 빈번하지만,
'I → 9', 'O → 0'처럼 문자가 숫자로 인식되는 경우는 상대적으로 희귀한 패턴을 가집니다.
따라서 'AA#AAA-######'형태와 'AAAAAA-######' 형태가 경쟁하는 경우, 숫자가 더 많이 포함된 Mask를 올바른 형태로 판단합니다.

경쟁에서 탈락한 Mask는 최종 Dictionary에 포함되지 않습니다.

---

## Token 유형

태그는 사전에 등록된 단어가 아니라 구조(Structure) 를 기준으로 먼저 분류됩니다.
각 Token Type은 서로 다른 Slot Grammar를 사용합니다 :

| type | example | slots |
|------|---------|-------|
| `instrument_tag` | `PIT-384220` | `[Measured Var][Function][Modifier]-[Loop][Suffix]` |
| `line_number` | `12"-VA-MQIEX-510275` | `[Pipe Size]-[Service]-[Area]-[Sequence]-[Spec]` |
| `equipment_tag` | `P-384210` | `[Letter(s)]-[Number]` |
| `drawing_reference` | `F4787-03` | `[Ref]-[Sheet]` |
| `nominal_pipe_size` | `50A` | `[Size][Unit]` |
| `annotation` | `NOTE1` | (not a tag) |

Instrument slots follow ISA-5.1-2024 Table 4 (`parse_instrument`):

```
PIT-384220
│││  └──── Loop number
││└────── Transmit   (T)
│└─────── Indicate   (I)
└──────── Pressure   (P, first letter)
```

---

## 평가 지표(Metrics)

Six metrics (`pid_tag_ocr.metrics`):

- Raw OCR Character Accuracy
- Grammar-constrained Character Accuracy
- Exact Tag Match
- Auto-approval Precision
- Rule-violation Detection Rate
- Human Review Rate

Ground Truth가 있는 경우:
- Character Accuracy
- Exact Match 를 계산합니다.
- 
Ground Truth가 없는 경우에는 'N/A'를 반환하여 근거 없는 성능 추정을 하지 않습니다.

---

## 표준 (Truth-based)

- **ANSI/ISA-5.1-2024**, *Instrumentation and Control – Symbols and Identification*
  — Table 4의 식별 문자(identification letters)를 `data/isa_5_1.json`으로 반영 (계기 태그용 L1 계층).
- **ISO 10628**, PFD/P&ID 도면 작성 규칙 — 라인 번호 슬롯 모델의 근거.
- **IEC 62424**, P&ID 제어 기능 표현 / 데이터 교환 — 기계 판독 가능한 구조화 추출의 근거.

세 표준 모두 `src/pid_tag_ocr/standards/references.py`에 정리되어 있으며, **하드 제약이 아닌 soft prior로만** 사용합니다.

---

## Layout

```
pid_tag_ocr/
├── pyproject.toml
├── build_grammar.py            # offline: caches -> grammar CSVs (mask competition)
├── data/
│   ├── isa_5_1.json            # ISA-5.1-2024 Table 4
│   └── grammar/                # induced dictionaries (read at runtime)
│       ├── grammar_masks.csv
│       ├── grammar_slots.csv
│       ├── grammar_vocab.csv
│       └── grammar_conf.csv
├── src/pid_tag_ocr/
│   ├── token_types.py          # structural token classifier
│   ├── grammar.py              # 4-layer hierarchical decoder
│   ├── metrics.py              # six metrics + confidence
│   ├── validate.py             # CLI: apply to a new drawing
│   └── standards/
│       ├── isa.py              # ISA-5.1 loader + instrument slot parser
│       └── references.py       # ISO 10628 / IEC 62424 documentation
└── tests/test_core.py
```
