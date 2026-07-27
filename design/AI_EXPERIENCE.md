# AI Experience

## 1. Product Role

Sage is a product layer, not a decorative chatbot.

Its job is to help users:

- understand what changed
- prioritize what matters
- decide with evidence
- draft where allowed
- verify what happened after action

## 2. Current AI Capabilities In The Repository

Supported today:

- grounded chat and streaming responses
- role-aware AI access controls
- optional voice transcription and synthesis
- executive briefing composition
- copilot feed generation
- decision and finding recommendations
- evidence and confidence metadata
- public AI ask endpoint for tenant-scoped embedding
- deterministic fallback behavior when model paths are unavailable

## 3. Canonical AI Modes

### 3.1 Read mode

Use cases:

- Today
- Executive Briefing
- Copilot feed

Behavior:

- lead with summary
- highlight one primary issue
- expose evidence on demand

### 3.2 Ask mode

Use cases:

- global chat panel
- copilot ask box
- voice input
- public embedded ask experience

Behavior:

- answer grounded questions
- preserve tenant and role scope
- suggest meaningful next questions

### 3.3 Recommend mode

Use cases:

- Decisions
- Insights
- Value
- Procurement suggestions

Behavior:

- connect a fact pattern to a recommended action
- explain expected impact and confidence

### 3.4 Draft mode

Use cases:

- Action Drafts
- finding-to-action path

Behavior:

- reduce manual effort
- require explicit user review before action

### 3.5 Measure mode

Use cases:

- decision outcomes
- finding outcomes
- briefing win/progress language

Behavior:

- report whether change improved, worsened, or has not moved enough yet

## 4. Answer Anatomy

Every user-facing AI answer should try to present, in this order:

1. verdict or direct answer
2. supporting evidence
3. confidence or certainty framing
4. scope and freshness
5. recommended next step

Do not start with long explanation when a direct answer exists.

## 5. AI Surface Rules

### 5.1 Today

- AI is a guide, not the entire page
- show one clear recommendation first
- avoid full conversational density in the hero area

### 5.2 Executive Briefing

Required structure:

- verdict
- what needs you
- key numbers
- why it moved
- what to watch
- measured progress or win

### 5.3 Global Chat Panel

Required behavior:

- preserve conversation context within the current session
- keep scope visible
- provide evidence chips or citations when available
- allow users to pivot into the underlying page or object

### 5.4 Copilot

- combine proactive feed and ask entry
- use focus chips to frame the conversation
- keep feed modules actionable, not inspirational

### 5.5 Workflow Surfaces

When AI participates in a workflow object, expose:

- recommendation
- impact
- confidence
- evidence
- allowed next actions

### 5.6 Developer Surfaces

- AI may assist explanation and examples
- AI must not fabricate API shapes or unsupported parameters
- contract truth beats conversational fluency

## 6. Trust And Safety Rules

### 6.1 Grounding

- no invented metrics
- no implied access to hidden data
- no scope leakage across tenants or roles
- no unsupported action promises

### 6.2 Permission boundaries

When blocked by permission:

- say so clearly
- avoid hinting at hidden underlying values
- route the user to the right surface or role if appropriate

### 6.3 Low-confidence behavior

When confidence is weak:

- narrow the answer
- explain what is missing
- recommend the next best page or investigation path

## 7. Transparency Model

Show when available:

- confidence
- freshness or timing context
- evidence facts
- whether the result is measured vs predicted
- the recommended next step

Do not show:

- raw prompts
- internal chain noise
- unnecessary implementation details for normal users

## 8. Voice Rules

Voice is additive, not mandatory.

Rules:

- voice controls must have typed equivalents
- voice capture must show clear active/inactive state
- transcript review should precede consequential actions
- voice should not bypass role or permission checks

## 9. Accessibility Requirements

- streaming answers must announce politely, not constantly interrupt
- suggested prompts must be keyboard reachable
- transcripts must remain readable and navigable
- confidence and status cannot rely on color alone
- focus must move predictably between ask box, transcript, and cited objects

## 10. Future Enhancements

- `[Future Enhancement]` saved prompts and role-specific playbooks
- `[Future Enhancement]` broader cross-surface AI memory with explicit controls
- `[Future Enhancement]` richer voice briefing mode for mobile and commute use
- `[Future Enhancement]` policy-gated higher-autonomy execution after governance hardening
