# Citadel

Citadel is an organization knowledge context for shared, source-linked company memory. This language keeps product concepts distinct from storage, implementation, and integration mechanisms.

## Language

**Organization Vault**:
A cloud-hosted, access-controlled shared memory layer for humans and agents.
_Avoid_: knowledge base, database, company Obsidian

**Source Material**:
Raw company material that may be used to produce structured knowledge.
_Avoid_: knowledge, truth, memory

**Source Snapshot**:
The retained evidence or source pointer used to reproduce what the **Organization Vault** learned from **Source Material**.
_Avoid_: permanent dump, backup, index record

**Vault Backup Mirror**:
A secondary synced copy of vault evidence and history used for recovery, audit, and rebuilds.
_Avoid_: source of truth, runtime store, live index

**Structured Knowledge**:
Source-linked company knowledge that has been organized into explicit concepts, relationships, and context.
_Avoid_: raw data, unprocessed sync, dump

**Knowledge Index**:
A searchable organization of **Structured Knowledge** for fast retrieval.
_Avoid_: database, file store, raw storage

**Knowledge Mesh**:
A relationship map that connects **Structured Knowledge** by source, concept, and provenance.
_Avoid_: decorative graph, chat history, raw sync map

**Learning Process**:
The governed transformation of **Source Material** into **Structured Knowledge**.
_Avoid_: self-learning, magic sync, auto-truth

**Tiered Ingestion**:
Org-bound syncs receive full processing (security review, enrichment, and structuring); raw seat-**Node** agent memory receives lighter indexing only.
_Avoid_: same pipeline for all content, skip processing, full enrichment everywhere

**Vault Member**:
A human participant who has permission to access an **Organization Vault**.
_Avoid_: user, teammate, account

**Seat**:
A licensed team member slot; equals one **Principal** (one human, one seat). Created by admin before **Tokens** are issued.
_Avoid_: user account, shared login, license bundle

**Node**:
A seat's private mini knowledge base; logically isolated storage for that seat's agent memory. **Nodes** do not collide; seats cannot read each other's **Nodes**.
_Avoid_: organization vault, central, shared memory

**Central**:
The organization-wide shared knowledge base. Distinct from any seat **Node**.
_Avoid_: seat node, personal vault, private agent memory

**Token**:
The credential a **Seat** uses to access their **Node** (and **Central** per read rules). Not the storage boundary — the **Node** is.
_Avoid_: node, storage scope, MCP key

**Agent Identity**:
A non-human actor that uses agent messaging for communication and may access an **Organization Vault**.
_Avoid_: bot, autonomous agent, service user

**Agent Messenger**:
The communication layer used by **Agent Identities** to exchange messages with each other.
_Avoid_: vault chat, shared memory, organization vault, MCP

**Access Token**:
A revocable credential that lets a **Vault Member** or **Agent Identity** access an **Organization Vault**.
_Avoid_: MCP key, shared password, API secret

**Access Role**:
A named permission level that determines what a **Vault Member** or **Agent Identity** may do in an **Organization Vault**.
_Avoid_: read me access, write access key

**Agent Action**:
A vault operation performed by an **Agent Identity**.
_Avoid_: background magic, unrestricted automation

**Vault Contribution**:
Structured or source-linked knowledge added to an **Organization Vault** by an actor with write permission.
_Avoid_: chat message, random update, raw agent conversation

**Promotion**:
A curated copy of content from a seat **Node** into **Central**. Dual-write: the original stays in the **Node**; the copy goes to **Central**.
_Avoid_: move, delete original, automatic merge

**Automatic + Curated Sync**:
Default agent memory stays in the seat **Node**; org-bound content (pipelines, tagged contributions) also lands in **Central** per curation rules.
_Avoid_: full vault mirror, seat-to-seat sync, chat log sync

**Repository Daily Update**:
A source-linked summary of meaningful changes in one repository over a day.
_Avoid_: employee report, department update, surveillance

**Meaningful Source Change**:
A source-linked change that affects work visibility, product behavior, architecture, reliability, decisions, blockers, or active repository momentum.
_Avoid_: raw activity, commit spam, productivity tracking

**Organization Update Digest**:
A source-linked summary of meaningful changes, features, decisions, and ongoing work produced from the **Organization Vault**.
_Avoid_: chat transcript, people report, raw activity feed, surveillance

**Security Finding**:
A source-linked, redacted report of a potential secret exposure or high-risk issue that requires team attention.
_Avoid_: secret dump, raw match, vague warning

**Knowledge Conflict**:
A visible disagreement between pieces of **Structured Knowledge** or their supporting **Source Snapshots**.
_Avoid_: merge, overwrite, silent correction

## Relationships

- An **Organization Vault** is accessed by humans and agents.
- An **Organization Vault** contains **Structured Knowledge**.
- **Source Material** becomes useful to the **Organization Vault** through a **Learning Process**.
- A **Source Snapshot** preserves enough evidence to cite, audit, or reprocess **Structured Knowledge**.
- A **Vault Backup Mirror** keeps a redundant copy of vault evidence without serving live retrieval.
- A **Learning Process** produces **Structured Knowledge**, a **Knowledge Index**, and a **Knowledge Mesh**.
- A **Vault Member** or **Agent Identity** uses an **Access Token** to access an **Organization Vault**.
- An **Access Role** limits what a **Vault Member** or **Agent Identity** may read or change.
- An **Agent Action** is constrained by the **Agent Identity**'s **Access Role**.
- An **Agent Identity** communicates with other **Agent Identities** through the **Agent Messenger**.
- A **Vault Member** or **Agent Identity** with write permission may create a **Vault Contribution**.
- **Agent Messenger** messages do not become **Vault Contributions** unless an actor with write permission adds them.
- A **Repository Daily Update** summarizes repository changes, not individual people.
- A **Repository Daily Update** is composed from **Meaningful Source Changes** in one repository.
- An **Organization Update Digest** can include one or more **Repository Daily Updates** plus other source-linked changes from the **Organization Vault**.
- An **Organization Update Digest** highlights **Meaningful Source Changes** across repositories and other approved sources over a defined time window.
- An **Organization Update Digest** can be delivered to an external communication surface without becoming **Source Material** itself.
- A **Security Finding** is separate from an **Organization Update Digest** and should never expose secret values in external communication surfaces.
- A **Knowledge Conflict** should be shown when source-linked knowledge disagrees.
- A **Seat** is one human **Principal** that may hold several **Tokens**; **Agent Identities** acting for that human are separate principals that may be granted access to the seat's **Node**.
- A caller is treated as holding a **Node** when a seat **Node** is in its access scope — this is what subjects it to **Central** curation rules, regardless of whether it is the human seat-holder or one of their agents.

## Example Dialogue

> **Dev:** "Should this GitHub repository be added to the database?"
> **Domain expert:** "Add it as **Source Material**. It becomes **Structured Knowledge** only after the **Learning Process** extracts useful context from it."
>
> **Dev:** "Can we search new material immediately?"
> **Domain expert:** "Only after the **Learning Process** has made it part of the **Knowledge Index** and **Knowledge Mesh**."
>
> **Dev:** "Do we keep the raw material forever?"
> **Domain expert:** "No. Keep a **Source Snapshot** when it is needed for citation, audit, or reprocessing; keep the **Knowledge Index** and **Knowledge Mesh** rebuildable."
>
> **Dev:** "Should the backup repository be the live knowledge store?"
> **Domain expert:** "No. The **Vault Backup Mirror** is redundant storage for recovery and rebuilds, not the runtime vault."
>
> **Dev:** "Should every teammate get an MCP key?"
> **Domain expert:** "Give each **Vault Member** or **Agent Identity** its own **Access Token** with the right **Access Role**."
>
> **Dev:** "Do agents talk to each other through the Organization Vault?"
> **Domain expert:** "No. **Agent Identities** communicate through the **Agent Messenger** and use the **Organization Vault** as shared memory."
>
> **Dev:** "Can an agent save something it discussed with another agent?"
> **Domain expert:** "Yes, if its **Access Role** allows writes, it can create a **Vault Contribution**."
>
> **Dev:** "What can an agent do without approval?"
> **Domain expert:** "Reader agents can read and search. Writer agents can add contributions, submit feedback, and provide updates."
>
> **Dev:** "Should daily updates say what each person did?"
> **Domain expert:** "No. A **Repository Daily Update** summarizes meaningful changes in one repository."
>
> **Dev:** "What belongs in a repository daily update?"
> **Domain expert:** "Meaningful commits, pull requests, and repository changes."
>
> **Dev:** "Should the digest list every commit from the last day?"
> **Domain expert:** "No. It should highlight **Meaningful Source Changes**, especially open pull requests, merged work, active repositories, blockers, and the vault's source-linked interpretation of the last 24 hours."
>
> **Dev:** "Should the Google Chat bot summarize what everyone said in chat?"
> **Domain expert:** "No. It should deliver an **Organization Update Digest** from source-linked vault context, not turn chat transcripts into vault memory."
>
> **Dev:** "If a future PR check finds an API key, should the digest post it?"
> **Domain expert:** "No. Create a **Security Finding** with redacted details and link to the GitHub check; never post the secret value."
>
> **Dev:** "What if a note disagrees with a newer repository change?"
> **Domain expert:** "Prefer the newer source-linked repository truth for code behavior, but keep a visible **Knowledge Conflict**."

## Flagged Ambiguities

- "knowledge base" and "database" were used for the same product concept; resolved: the product concept is **Organization Vault**.
- "raw data retention" was unclear; resolved: keep **Source Snapshots** for citation, audit, and reprocessing, while treating indexes and mesh structures as derived.
- "knowledge sync repository" sounded like a source of truth; resolved: the canonical term is **Vault Backup Mirror**, a redundant copy for recovery, audit, and rebuilds.
- "self-learning" was used to mean automatic structuring of raw inputs; resolved: the domain term is **Learning Process**.
- "indexed mesh" was used to describe retrieval; resolved: **Knowledge Index** supports search, while **Knowledge Mesh** represents relationships.
- "MCP key" and "access token" were used for credentials; resolved: the domain term is **Access Token**.
- "department-scoped access" was considered for the first version; resolved: initial **Access Tokens** grant whole-vault access constrained by **Access Role**.
- "agent action approval" was broad; resolved: read/search is open to reader agents, writer agents may contribute, submit feedback, and provide updates, while sensitive admin actions stay gated.
- "agent identity" was used as if it only meant vault access; resolved: **Agent Identities** communicate through the **Agent Messenger** and access the vault separately.
- "agent messenger" was used near shared memory; resolved: **Agent Messenger** is the communication layer, while the **Organization Vault** is the shared memory layer.
- "agent messages" were discussed as possible vault content; resolved: messages stay in **Agent Messenger** unless an actor with write permission creates a **Vault Contribution**.
- "daily update" was initially broad; resolved: daily updates are **Repository Daily Updates**, not people or department reports.
- "repository daily update detail" was too broad; resolved: include meaningful commits, pull requests, and repository changes only.
- "meaningful change" was vague; resolved: **Meaningful Source Changes** are source-linked changes around pull requests, merged work, repository momentum, blockers, decisions, reliability, architecture, or product behavior.
- "org update" was broader than repository changes; resolved: an **Organization Update Digest** summarizes meaningful source-linked changes, features, decisions, and ongoing work from the **Organization Vault**.
- "secret reporting" was initially mixed into the update digest; resolved: potential secrets and high-risk issues are **Security Findings**, redacted and handled separately from daily digests.
- "conflicting knowledge" was unresolved; resolved: prefer newer source-linked repository truth for code behavior, while marking **Knowledge Conflicts** visibly.
- "is a caller a Seat?" was conflated with principal identity; resolved: for **Central** curation the test is whether a seat **Node** is in the caller's access scope, which covers both the human's **Tokens** and their **Agent Identities** — agents are not the human **Principal** and so carry no seat marker of their own.
