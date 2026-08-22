# Define the model comparison and winning evidence

Type: grilling
Status: resolved
Blocked by: 03, 07, 09, 10

## Question

Which exact models, scenario splits, repeated seeds, metrics, uncertainty reporting, and acceptance thresholds constitute fair evidence that the trained Gemma improved over base Gemma and is meaningfully competitive with a frontier model? Rule out prompt, tool, data-leakage, and evaluation asymmetries that could manufacture the result.

## Decision

Run base Gemma E4B, the reloaded trained E4B adapter, GPT, and Gemini through the same canonical scenarios, tools, hidden state, budgets, and deterministic scoring, using provider-native adapters only at the model seam. The primary winning evidence is a positive paired held-out EEG task-success difference for trained versus base Gemma whose 95% bootstrap confidence interval excludes zero. Also report verifier score, abort precision/recall, action count, tool errors, and individual/ambiguous/pair/triple strata. GPT and Gemini are labeled reference results; trained Gemma need not beat them. Mesoscope results are a separate platform-generality track and do not determine the EEG training win.
