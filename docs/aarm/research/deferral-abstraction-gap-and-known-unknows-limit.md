# Academic Backing 整理: AARM DEFER Abstraction Gap and the Known-Unknowns Limit on Deferral

## TL;DR

- **Gap 1 (abstraction gap between narrative FRAMEWORK deferral and operational R3 conformance triggers) is well-grounded but not novel:** it is a specific instance of a phenomenon that standards-drafting doctrine (ISO/IEC Directives Part 2; W3C QA Framework) and requirements engineering (goal-oriented RE; Jackson–Zave; retrenchment) already treat as a routine, expected feature — informative/narrative rationale legitimately says more than the objectively-verifiable conformance clauses, and conformance is judged only against the verifiable subset. No single source states the AARM reading directly; it is a composition.
- **Gap 2 (deferral coherent only for known-unknowns) has a strongly-grounded structural core but a partly-novel strong form:** decision theory rigorously supports that value-of-information is defined only over a represented state space and that unawareness needs a categorically different operation (Howard 1966; Dekel–Lipman–Rustichini 1998; Quiggin 2016). But no source asserts the *operational* claim in AARM's terms, and the ML reject-option literature (Hendrickx et al. 2024) *partially contradicts* the strongest form, because novelty/out-of-distribution rejection is a recognized legitimate abstention response to unknown-unknowns — just not a "postpone-for-a-named-field" one.
- **Verdict:** the refined reading sits **between "solidly grounded" and "novel."** Both gaps rest on strong, citable, foundational literatures, but only by *composition*, and none of those sources concerns autonomous-agent runtime governance or AARM. The genuine contribution is the *mapping*, not the underlying concepts; document it as an application of established results, not as something those results were derived for.

---

## Scope and Framing

This note supplies targeted academic backing for two specific readings of the AARM specification (Autonomous Action Runtime Management, Herman Errico / Cloud Security Alliance, 2026, arXiv:2602.09433), treating the interpretation as an **internal tension within the AARM paper itself** between (a) the FRAMEWORK chapter's narrative/abstract description of DEFER (§IV-B-4, four situations including "composite risk unclear given incomplete action history" and "actions whose safety depends on information not yet available in the session") and (b) the CONFORMANCE REQUIREMENTS chapter's operational R3 triggers (match-predicate references an unpopulated context field; multiple same-priority policies conflict; confidence below threshold). It deliberately does not re-open topics already handled (runtime-verification monitorability, the Fernandez 2026 series, awareness logics as a general topic, AARM's citation absence). Non-existence findings are stated explicitly. Strength ratings are conservative and distinguish genuine precedent from loose analogy.

---

## GAP 1 — The Abstraction Gap Between Narrative Requirement Descriptions and Verifiable Conformance Requirements

**The AARM reading:** The FRAMEWORK narrative prose is broad enough to encompass unknown-unknowns, while the R3 conformance triggers only capture known-unknowns plus policy conflict and confidence threshold. Situations #3/#4 therefore do not map cleanly onto R3(a)(b)(c). The gap is between an abstract/narrative requirement statement and a concrete/verifiable conformance clause.

There is a substantial, mature literature on exactly this phenomenon. It is not a novel observation; it is a well-recognized structural feature of normative documents.

### 1A. Requirements engineering: goals/rationale vs. verifiable requirements

**Named concepts:** goal-oriented requirements engineering (GORE); goal refinement/operationalization; requirements completeness "with respect to a set of goals"; the goals-vs-scenarios contrast.

**Key citations:**
- A. van Lamsweerde, "Goal-Oriented Requirements Engineering: A Guided Tour," Proc. RE'01, 5th IEEE Int'l Symposium on Requirements Engineering, 2001, pp. 249–263. It states the completeness criterion verbatim: "Goals provide a precise criterion for sufficient completeness of a requirements specification; the specification is complete with respect to a set of goals if all the goals can be proved to be achieved from the specification and [known domain properties]." It also names the register contrast directly: "scenarios and goals have complementary characteristics; the former are concrete, narrative, procedural, and leave intended properties implicit; the latter are abstract, declarative, and make intended properties explicit."
- A. Dardenne, A. van Lamsweerde, S. Fickas, "Goal-directed requirements acquisition," Science of Computer Programming 20 (1993), 3–50 (the KAOS foundation).
- A. van Lamsweerde, "Requirements Engineering: From System Goals to UML Models to Software Specifications," Wiley, 2009 (textbook consolidation).

**Strength rating: STRONG (structurally), PARTIAL as a direct match.** GORE precisely names the layering the AARM reading invokes — high-level narrative rationale (goals) that must be *operationalized* into concrete, checkable requirements, with completeness defined relative to whether the operational level discharges the goals. The AARM tension is exactly a case where the operationalization (R3) under-covers the goal-level narrative (§IV-B-4), and van Lamsweerde's own words — narrative/procedural material that "leaves intended properties implicit" — describe §IV-B-4's prose well. The caveat: GORE frames this as a normal *refinement obligation* to be discharged, not as a pathological "gap." So GORE backs the *vocabulary and existence* of the gap strongly, but treats it as routine.

### 1B. Jackson & Zave: requirements vs. specifications, world vs. machine

**Named concepts:** the requirement/specification distinction; the "world vs. machine" framing; domain knowledge K as the bridge (S, K ⊢ R); indicative vs. optative descriptions; private vs. shared phenomena.

**Key citations:**
- P. Zave and M. Jackson, "Four Dark Corners of Requirements Engineering," ACM Transactions on Software Engineering and Methodology (TOSEM) 6(1), January 1997, pp. 1–30. DOI: 10.1145/237432.237434.
- M. Jackson and P. Zave, "Deriving Specifications from Requirements: An Example," Proc. 17th ICSE, 1995, pp. 15–24.
- C. A. Gunter, E. L. Gunter, M. Jackson, P. Zave, "A Reference Model for Requirements and Specifications," IEEE Software 17(3), 2000, pp. 37–43.

**Strength rating: PARTIAL / LOOSE.** The Jackson–Zave distinction is highly relevant to one *specific* sub-point: a specification may only constrain machine-controlled, *shared* phenomena "without reference to the future," whereas requirements are typically about *private* phenomena the machine cannot directly sense. This maps onto the AARM detail that the *runtime system* (the machine) detects "a referenced field is not yet populated," while the abstract requirement is stated over world-level notions of "safety" and "risk." It supports the general thesis that a narrative (world-level) requirement systematically exceeds what a machine-checkable specification can capture. However, Jackson–Zave concerns the requirement→specification derivation *within one artifact set*, not an intra-document tension between two prose registers, so it is an analogy rather than a precise precedent.

### 1C. Standards/RFC practice: normative conformance language vs. informative narrative

**Named concepts:** the normative/informative distinction; RFC 2119 MUST/SHOULD/MAY keywords; conformance clauses and test assertions; the requirement that only objectively verifiable statements carry conformance force.

**Key citations:**
- S. Bradner, "Key words for use in RFCs to Indicate Requirement Levels," RFC 2119 / BCP 14, IETF, March 1997.
- ISO/IEC Directives, Part 2 (9th ed., 2021), §3.3.3 defining a *requirement* as an "expression … that conveys objectively verifiable criteria to be fulfilled and from which no deviation is permitted if conformance with the document is to be claimed," and the rule "Requirements shall be objectively verifiable. Only those requirements that can be verified shall be included." Also the neutrality principle: documents that "do not contain requirements (i.e. do not contain the verbal expression 'shall') are not intended to be used for conformity assessment."
- W3C QA Framework: Specification Guidelines (W3C Recommendation), which distinguishes normative from informative text, requires "Write test assertions" (Good Practice 12), derives a normative test assertion from each MUST requirement, and states that informative text "does not determine whether an implementation passes or fails conformance."

**Strength rating: STRONG.** This is the closest and most directly on-point body of precedent. The ISO/IEC Directives and the W3C QA Framework institutionalize *exactly* the two-register structure the AARM reading describes: (1) informative/narrative text supplying motivation and rationale (AARM §IV-B-4's prose), and (2) normative conformance clauses expressed as objectively verifiable MUST-triggers (AARM R3), with an explicit doctrine that only the verifiable subset carries conformance force. The standards community's own drafting rules presuppose that narrative can and does say more than the testable clauses — which is precisely why they mandate that conformance be judged *only* against the verifiable clauses. This strongly backs the reading that R3 legitimately under-covers §IV-B-4, and that this is a recognized (indeed deliberately managed) feature of well-drafted specifications rather than an authorial slip. Nuance: standards doctrine treats the split as *intentional design*, so the §IV-B-4↔R3 mismatch is better characterized as **under-specification / informative over-reach** than as a contradiction.

### 1D. Formal methods: refinement gaps and retrenchment

**Named concepts:** data/operation refinement; property preservation under refinement; the limitation that classical refinement is too strong for many realistic abstract→concrete steps; **retrenchment** as the explicit formalism for the residue refinement cannot capture.

**Key citations:**
- R. Banach and M. Poppleton, "Retrenchment: An Engineering Variation on Refinement," Proc. B'98, LNCS 1393, Springer, 1998, pp. 129–147. The abstract argues refinement "is too restrictive to describe all but a fraction of many realistic developments" and proposes retrenchment, "which allows only a fraction of the high level behaviour to be captured at the low level."
- R. Banach, C. Jeske, M. Poppleton, S. Stepney, later retrenchment work (Science of Computer Programming; the "Retrenching the purse"/Mondex case studies).
- General refinement references: J. Woodcock and J. Davies, "Using Z: Specification, Refinement and Proof," Prentice-Hall, 1996; C. Morgan, "Programming from Specifications," Prentice-Hall.

**Strength rating: PARTIAL, and the most conceptually precise analogue for the "gap" itself.** Retrenchment is the formal-methods concept that most exactly names the AARM phenomenon: an abstract-level description whose full content is *deliberately* only partially captured at the concrete/implementable level, with the un-captured residue made explicit (via "within" and "concedes" predicates). The AARM reading — abstract §IV-B-4 behavior that concrete R3 clauses capture only in part — is structurally a retrenchment rather than a refinement. Strong conceptual fit for *characterizing the gap*; but it is imported from program/data refinement, not a result about natural-language requirement/conformance documents. Flag for the careful reader: retrenchment presupposes both levels are formal models, whereas §IV-B-4 is natural-language prose, so the mapping is by analogy.

**Gap 1 non-existence finding:** I found **no** literature that specifically studies the tension between an *abstract narrative requirement* and a *concrete conformance requirement* **within a single specification document for autonomous-agent runtime governance**, nor any that treats "narrative deferral situations exceed conformance triggers" as a named pattern. The backing is by composition of four established literatures (GORE, Jackson–Zave, standards conformance doctrine, retrenchment), each supporting a facet. No single source states the AARM reading directly.

---

## GAP 2 — Deferral/Abstention Is Coherent Only for Known-Unknowns, Not Unknown-Unknowns

**The AARM reading (a reversal from the first pass):** DEFER as an operational decision to postpone and gather more information is coherent *only* for known-unknowns — the referenced-but-unpopulated field, where the system knows *what* it is waiting for. For genuine unknown-unknowns (relevance not representable in any policy), deferral is not coherent because there is nothing specific to wait for; such cases fall outside a defer mechanism's scope. The FRAMEWORK prose over-reaches into unknown-unknowns that no defer trigger can operationalize.

### 2A. Value of information (VoI) theory — the limiting reading

**Named concepts:** value of information / EVPI; VoI defined over an enumerated, mutually-exclusive-and-exhaustive outcome/state space with assigned probabilities; the impossibility of representing unawareness in standard state-space models; "value of awareness" (VOA) as the distinct quantity capturing gains from expanding the state space.

**Key citations:**
- R. A. Howard, "Information Value Theory," IEEE Transactions on Systems Science and Cybernetics, vol. 2(1), 1966, pp. 22–26. DOI: 10.1109/TSSC.1966.300074. The VoI computation is defined as the expected gain from resolving uncertainty over an *already-specified* set of outcomes with assigned probabilities. (The "state space is given" point is structural/implicit in the VoI formalism, not a quotable thesis sentence in Howard; it is stated explicitly only in the later awareness literature below.)
- E. Dekel, B. L. Lipman, A. Rustichini, "Standard State-Space Models Preclude Unawareness," Econometrica 66(1), Jan. 1998, pp. 159–174. DOI: 10.2307/2998545. The canonical impossibility result: "if an agent is unaware of some possibility, he must not fully understand the state space. The way we usually work with state-space models requires the agent to have more understanding of the state space than unawareness allows." Under Necessitation, Plausibility, and KU/AU Introspection, unawareness is contradictory — glossed as: "if the agent is unaware of anything, he is unaware of everything and knows nothing."
- J. Quiggin, "The value of information and the value of awareness," Theory and Decision 80(2), Feb. 2016, pp. 167–185. DOI: 10.1007/s11238-015-9496-x. Defines VOA analogous to VOI and proves, verbatim, that "the sum VOA + VOI is constant and, except for scale effects, independent of the choice set. It follows that the larger is VOA, the smaller is VOI." I.e., VoI operates only over states one is already aware of; the gain from expanding the space is a *separate* quantity (VOA).
- Supporting: S. Modica and A. Rustichini, "Awareness and Partitional Information Structures," Theory and Decision 37(1), 1994, pp. 107–124 (cite for "standard uncertainty cannot capture inability to describe the states"; their 1999 Games and Economic Behavior paper is a *partial workaround*, not a flat impossibility, so cite it carefully).

**Strength rating: STRONG.** This is the strongest and most rigorous backing for the entire Gap-2 limiting claim. VoI is *definitionally* computed over a represented state/hypothesis space (Howard 1966); Dekel–Lipman–Rustichini prove that a standard state space *cannot* represent genuine unawareness; and Quiggin shows the value of resolving in-model uncertainty (VOI) and the value of expanding the model (VOA) are complementary and distinct. Translated to AARM: DEFER-to-gather-information is exactly a VoI-style move — it presupposes a represented "field" whose value is missing (a known-unknown). For an unknown-unknown, the relevant "state" is not in the model, so no VoI can be computed and there is nothing to wait for. This is genuine strong precedent, not analogy — with the honest caveat that these authors write about idealized decision-theoretic agents, and none mentions AARM, deferral mechanisms, or runtime governance; the application is ours.

### 2B. Selective prediction / reject option / learning to defer

**Named concepts:** the reject option (Chow 1970); ambiguity rejection vs. novelty rejection; selective classification; learning to defer; the alignment of rejection type with aleatoric vs. epistemic uncertainty.

**Key citations:**
- K. Hendrickx, L. Perini, D. Van der Plas, W. Meert, J. Davis, "Machine Learning with a Reject Option: A Survey," Machine Learning 113(5), 2024, pp. 3073–3110. DOI: 10.1007/s10994-024-06534-x (arXiv:2107.11277). Formalizes two rejection types: **ambiguity rejection** (instance near the decision boundary — an in-distribution, identified source of uncertainty) and **novelty rejection**, defined verbatim as "occurs if x falls in a region where there was little (or no) training data. Hence, the predictor may struggle to make accurate predictions because it did not see enough data to accurately model the relationship between X and Y."
- C. K. Chow, "On optimum recognition error and reject tradeoff," IEEE Trans. Information Theory 16(1), 1970, pp. 41–46 (the seminal reject option).
- R. El-Yaniv and Y. Wiener, "On the foundations of noise-free selective classification," JMLR 11, 2010, pp. 1605–1641; Y. Geifman and R. El-Yaniv, "Selective Classification for Deep Neural Networks," NeurIPS 2017.
- D. Madras, T. Pitassi, R. Zemel, "Predict Responsibly: Improving Fairness and Accuracy by Learning to Defer," NeurIPS 2018 (learning to defer routes uncertain inputs to an external expert).

**Strength rating: PARTIAL — supports the *distinction*, only loosely supports the *limiting claim*.** The ambiguity/novelty distinction (Hendrickx et al. 2024) maps cleanly onto AARM's known-unknown vs. unknown-unknown split: ambiguity rejection resembles R3(b)/(c) (conflict / low confidence within a represented space), and novelty rejection resembles the unknown-unknown case. Crucially, the literature ties rejection *type* to uncertainty *type* and to whether more data helps: **epistemic** uncertainty (reducible; a known-unknown once its source is identified) motivates *acquiring more observations*, whereas **aleatoric** uncertainty cannot be resolved by more of the same data — a distinction Hendrickx et al. (2024) make central. This backs "defer-to-gather-info only makes sense when the missing information is identifiable." However — important honest caveat — the ML literature does **not** say deferral is *ill-posed* or *out of scope* for novelty/unknown-unknown cases. On the contrary, novelty rejection *is* a recognized and desirable abstention (abstain-and-flag) for OOD inputs. So the ML framing supports AARM's *distinction* strongly but *contradicts* the strong form of AARM's claim that unknown-unknowns fall entirely outside a defer mechanism. The reconciliation: AARM's DEFER specifically means *postpone-and-acquire-specified-information*, which is the ambiguity/epistemic case; a *reject-and-escalate* response to novelty is a different action (closer to AARM's presumable DENY/escalate path), not DEFER.

### 2C. Active learning — you can only query what you can represent

**Named concepts:** membership query synthesis; pool-based sampling; stream-based selective sampling; the version space; the fixed instance space X and label set Y.

**Key citations:**
- B. Settles, "Active Learning Literature Survey," Computer Sciences Technical Report 1648, University of Wisconsin–Madison, 2009 (and Morgan & Claypool, 2012). All three query scenarios presuppose a pre-defined instance/query space; pool-based sampling draws from "a base pool of instances," and membership query synthesis lets the learner request the label of any data point belonging to the (already-defined) input space or a synthetically generated one.
- T. M. Mitchell, "Generalization as Search," Artificial Intelligence 18(2), 1982 (version space).

**Strength rating: PARTIAL (illustrative, by demonstration).** Active learning structurally embodies "you can only defer-to-acquire what you can already name": every query strategy is defined over a fixed, representable instance/feature space. A clean *illustration* of the same presupposition in a different field. Honest caveat: Settles does not frame this as a *limitation* concerning unknown-unknowns; it is simply the standard problem setup. It supports the reading by demonstration, not by an explicit thesis that acquisition is *ill-posed* outside that space.

### 2D. Explicit decision-theoretic / epistemic line drawing

**Named concepts:** unawareness; unforeseen contingencies; bounded awareness; reverse Bayesianism / extended Bayesianism.

**Key citations:**
- S. Grant and J. Quiggin, "Inductive reasoning about unawareness," Economic Theory 54(3), 2013, pp. 717–755.
- E. Piermont, "Unforeseen Evidence" (arXiv:1907.07019) — extended Bayesianism for updating when one becomes aware of new contingencies.
- Dekel–Lipman–Rustichini 1998 (as above).

**Strength rating: PARTIAL.** This literature rigorously establishes that unknown-unknowns (unawareness) cannot be handled by standard within-model machinery and require *expanding* the model — a qualitatively different operation than resolving in-model uncertainty. That directly supports the structural claim behind the AARM reading. But I found **no source that states, in the specific operational terms AARM uses, "deferring to acquire information is rational only when the missing information is identified/known-unknown; unknown-unknowns cannot be resolved by deferral."** The decision-theory literature draws the awareness/information line and shows the two are complementary (Quiggin), which *implies* the AARM claim, but does not *assert* the operational-deferral version of it.

**Gap 2 non-existence finding:** There is **no** literature that directly asserts the operational claim "an autonomous agent's defer/postpone-and-gather action is well-posed only for known-unknowns and out of scope for unknown-unknowns." The strong form is *constructed* from decision theory (VoI/VOA complementarity; DLR impossibility) and ML (ambiguity/epistemic → acquire more data). Moreover, the ML reject-option literature *partially cuts against* the strongest form, because novelty/OOD rejection is a legitimate abstention response to unknown-unknowns — it just is not a *postpone-for-a-named-field* response.

---

## Synthesis: How Well-Grounded Is the Refined Reading?

**Gap 1 (abstraction gap):** *Well-grounded, and essentially a re-description of a known structural feature of specifications.* The single strongest precedent is standards-drafting doctrine (ISO/IEC Directives Part 2; W3C QA Framework), which formally separates informative/narrative rationale from objectively-verifiable normative/conformance clauses and mandates that conformance be judged only against the verifiable subset — exactly the §IV-B-4 (informative) vs. R3 (conformance) split. GORE supplies the goals-vs-operationalized-requirements vocabulary (and the "narrative/procedural, leaves properties implicit" characterization of §IV-B-4); retrenchment supplies the most precise *name* for a concrete level deliberately capturing only part of an abstract level; Jackson–Zave supplies the world/machine framing matching AARM's "runtime system detects the unpopulated field, the rule merely references it." The reading is therefore **not novel** as a phenomenon — it is a legitimate instance of under-specification / informative over-reach. What *is* arguably novel is applying this lens to an autonomous-agent runtime-governance spec's DEFER requirement.

**Gap 2 (deferral coherent only for known-unknowns):** *The structural core is strongly grounded; the strong operational form is partly novel and should be hedged.* Decision theory gives rigorous, non-analogical support that resolving uncertainty (VoI) is defined only over a represented state space and that unawareness requires a categorically different move (Howard 1966; Dekel–Lipman–Rustichini 1998; Quiggin 2016). ML reject-option and active-learning literatures independently exhibit the same presupposition and, via the epistemic-uncertainty → acquire-data linkage, support "defer-to-gather is well-posed only when the missing information is identifiable." **However**, no source states the operational deferral claim directly, and the ML literature mildly contradicts its strongest form (novelty/OOD abstention is a legitimate response to unknown-unknowns). Honest position: AARM's claim is *correct for its own precise definition of DEFER* and *strongly consistent with* decision theory, but it is a *synthesis*, not attachable to a single citation, and should not be over-generalized into "abstention is meaningless for unknown-unknowns."

**Overall:** The refined reading sits **between "solidly grounded" and "novel."** Both gaps are backed by strong, citable, foundational literatures — but by *composition*, and none of those sources is about autonomous-agent runtime governance or AARM. The contribution is the *mapping*, not the concepts.

---

## Recommendations

1. **Document Gap 1 primarily via standards-conformance doctrine.** Frame the §IV-B-4↔R3 relationship as the well-known informative-vs-normative split. Cite ISO/IEC Directives Part 2 (2021) §3.3.3 and the W3C QA Framework: Specification Guidelines as the primary backing, and describe the mismatch as **under-specification / informative over-reach**, not contradiction. Add GORE (van Lamsweerde RE'01) for the goals→operationalization vocabulary and retrenchment (Banach & Poppleton 1998) as the precise conceptual name — but label retrenchment explicitly as an analogy (it presupposes two formal models).
2. **Document Gap 2 primarily via decision theory.** Anchor on Howard (1966) for VoI-over-a-specified-space, Dekel–Lipman–Rustichini (1998) for the impossibility of representing unawareness in standard state spaces, and Quiggin (2016) for the VOA+VOI complementarity. State clearly that DEFER-to-acquire is a VoI-style move that presupposes a represented (known-unknown) field.
3. **Hedge the strong operational form of Gap 2.** Explicitly note that the ML reject-option literature (Hendrickx et al. 2024) recognizes *novelty rejection* as a legitimate abstention for OOD/unknown-unknown inputs; therefore state AARM's claim only for its narrow definition of DEFER (postpone-and-acquire-specified-information), and distinguish it from reject-and-escalate (a different action).
4. **Do not claim novelty for the phenomena; claim it for the mapping.** In the paper-reading interpretation, present both readings as *applications* of established results to AARM, not as claims those results were derived for.
5. **Benchmarks that would change these recommendations:** (a) If a source is found that treats "narrative requirement exceeds conformance clause" as a *named defect pattern* in agent-governance or safety specs, upgrade Gap 1 from "composition" to "direct precedent." (b) If a decision-theory or AI-safety source is found that *explicitly* states deferral/information-acquisition is ill-posed for unawareness (not merely that VoI is), upgrade Gap 2's strong form from "synthesis" to "direct precedent." (c) If AARM's own text defines a separate escalate/deny path for novelty, drop the Gap-2 hedge in 3 as moot.

---

## Caveats

- **No AARM-specific or agent-governance-specific source exists** for either reading; both are supported by composition of general literatures. Present accordingly.
- **Howard (1966):** the "state space is given" point is structural/implicit in the VoI formalism, not a quotable thesis sentence; the explicit statement lives in the awareness literature (DLR 1998; Quiggin 2016). A policy-permissible full text of Howard was not retrieved, so the pagination (pp. 22–26) and DOI are from reliable secondary sources.
- **Modica & Rustichini:** cite the 1994 *Theory and Decision* paper for the "standard uncertainty cannot describe the states" point; their 1999 *Games and Economic Behavior* paper is a partial workaround to the impossibility (it accommodates nontrivial unawareness under limited reasoning), not a flat impossibility result — do not cite it as the latter.
- **ML reject-option literature partially contradicts** the strongest form of the Gap-2 claim (novelty/OOD rejection is legitimate abstention for unknown-unknowns). This is the single most important qualification for a careful security engineer; the AARM claim survives only under AARM's narrow definition of DEFER.
- **Retrenchment and Jackson–Zave are analogies**, not direct precedents: retrenchment presupposes formal models on both levels; Jackson–Zave concerns requirement→specification derivation within one artifact set, not two prose registers in one document. Rate them accordingly.
- **Standards doctrine treats the informative/normative split as intentional design**, so calling the §IV-B-4↔R3 relationship a "tension" is a stronger word than the literature would use; "under-specification / informative over-reach" is the more defensible characterization.

### Explicit Non-Existence Flags (consolidated)

1. **No** source studies "narrative deferral situations exceeding conformance triggers" as a named pattern in agent-governance specifications.
2. **No** single source states the Gap-1 reading directly; it is a composition of GORE, Jackson–Zave, standards doctrine, and retrenchment.
3. **No** source asserts the operational claim "defer/postpone-and-gather is well-posed only for known-unknowns and out of scope for unknown-unknowns." It is implied by (not stated in) VoI/unawareness decision theory.
4. **No** clean verbatim "the state space is given" thesis sentence is recoverable from Howard (1966); the point is structural/implicit and stated explicitly only in later awareness literature (DLR 1998; Quiggin 2016).
5. The ML reject-option literature (Hendrickx et al. 2024) **partially contradicts** the strongest form of the Gap-2 claim: novelty/OOD rejection is a recognized legitimate abstention for unknown-unknowns, distinct from postpone-for-a-named-field deferral.