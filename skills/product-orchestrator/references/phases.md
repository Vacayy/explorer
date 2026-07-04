# Phase Templates

Each phase has defined inputs, outputs, and quality gates.

## Phase 1: 기획 (Product Planning)

**Expert**: Product Owner
**Input**: User's goal statement, existing product context
**Output**:
- `docs/PRD.md` — Problem, user, vision, metrics, scope (P0/P1/P2), out-of-scope
- Scope confirmation from stakeholder

**Quality gate**: Stakeholder approves scope. "Out of scope" section is explicit.

**Template prompt context**:
- Current product state (existing features, tech stack)
- Target user persona
- Business constraints (API limits, deployment model)

## Phase 2: 화면설계 (UX Specification)

**Expert**: UX Designer
**Input**: Approved PRD, existing UI patterns
**Output**:
- `docs/specs/{feature}.md` per screen — wireframe (ASCII), component table, interaction rules
- `docs/policies/{topic}.md` — cross-cutting rules (navigation, formatting, states)

**Quality gate**: Every screen defines 5 states (Empty, Loading, Partial, Error, Ideal).

**Template prompt context**:
- Approved PRD scope
- Existing shared components (`components/shared/`)
- Existing design tokens (CSS variables)
- Reference screenshots if available

## Phase 3: 디자인리뷰 (Design Review)

**Expert**: Design Lead
**Input**: Screen specs, current CSS/component code
**Output**:
- `docs/DESIGN_REVIEW.md` — Critique of palette, typography, layout density, chart colors
- Specific recommendations with hex values and font names

**Quality gate**: Recommendations are actionable (not "consider improving colors" but "#1B2559 for nav, #2563EB for links").

**Template prompt context**:
- Current `index.css` (design tokens)
- Current component implementations (read key files)
- Target user expectations (Bloomberg, FnGuide comparison)

## Phase 4: 백엔드 (Backend Engineering)

**Expert**: Backend Engineer
**Input**: Screen specs (data requirements), existing API patterns
**Output**:
- New/modified routers in `backend/routers/`
- New/modified DB tables in `backend/database.py`
- New/modified services in `backend/services/`
- Pydantic models in `backend/models/`

**Quality gate**: Backend loads without error (`python -c "from main import app"`).

**Template prompt context**:
- Screen spec's "Data Model" section (API shape, DB schema)
- Existing router patterns (copy style from working router)
- Existing service patterns (cache_service, dart_service)

## Phase 5: 프론트엔드 (Frontend Engineering)

**Expert**: Frontend Engineer
**Input**: Screen specs, backend API contract, existing component patterns
**Output**:
- New/modified page components
- New/modified hooks
- New/modified shared components
- Type definitions in `types/index.ts`

**Quality gate**: TypeScript compiles (`npx tsc --noEmit`).

**Template prompt context**:
- Screen spec's wireframe and component table
- Existing shared components to reuse
- Existing hooks pattern (useQuery/useMutation)
- shadcn/ui atoms available (`components/ui/`)

## Phase 6: 검증 (Verification)

**Expert**: QA Engineer
**Input**: Implemented feature, screen spec
**Output**:
- Type check result
- Critical path walkthrough (manual)
- Edge case audit against spec's 5-state definitions
- List of deviations from spec

**Quality gate**: Zero type errors. All 5 states handled. Critical path works end-to-end.
