"""DNS propagation render view."""

from ..ansi import BOLD, BRAND_AMBER, BRAND_MINT, BRAND_ROSE, BWHITE, DIM, c
from ..latency import latency_color
from ..tables import print_table


def print_result(result) -> None:
    majority = result.majority
    rows = []
    for a in result.answers:
        if not a.answered:
            status = c(a.status, BRAND_ROSE, BOLD)
            answer = c("—", DIM)
        else:
            status = c(a.status, BRAND_MINT if a.status == "NOERROR" else BRAND_AMBER)
            first = a.records[0] if a.records else "(no records)"
            differs = a.records != majority
            answer = c(first, BRAND_AMBER if differs else BWHITE)
            if len(a.records) > 1:
                answer += c(f"  +{len(a.records) - 1}", DIM)
        verdict = result.matches(a)
        mark = "" if verdict is None else (c("✔", BRAND_MINT) if verdict else c("✘", BRAND_ROSE))
        row = [c(a.resolver, BWHITE, BOLD), c(a.server or "system", DIM), status, answer]
        row.append(latency_color(a.elapsed_ms) if a.answered else c("—", DIM))
        if result.expected:
            row.append(mark)
        rows.append(row)
    headers = ["Resolver", "Server", "Status", "Answer", "Time"]
    if result.expected:
        headers.append("Match")
    print_table(headers, rows)
    print()

    answered = len(result.answered)
    if not answered:
        print(c("  ✘ No resolver answered.", BRAND_ROSE, BOLD))
    elif result.expected:
        ok = result.matching == answered
        color = BRAND_MINT if ok else BRAND_ROSE
        print(
            c(
                f"  {'✔' if ok else '✘'} {result.matching}/{answered} resolvers return the expected value",
                color,
                BOLD,
            )
        )
    elif result.consistent:
        print(c(f"  ✔ All {answered} resolvers agree", BRAND_MINT, BOLD))
    else:
        print(
            c(
                f"  ⚠ Resolvers disagree: {result.distinct_answers} distinct answers",
                BRAND_AMBER,
                BOLD,
            )
            + c("  (normal for CDNs / geo-DNS; use --expect to check a value)", DIM)
        )
    if len(majority) > 1:
        print(c("  Most common answer: ", DIM) + c(", ".join(majority), BWHITE))
    print()
