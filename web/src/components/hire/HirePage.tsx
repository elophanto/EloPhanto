import { useState } from "react";
import { ArrowRight, CheckCircle2, Clock3, Mail, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const email = "info@elophanto.com";
const mailto = `mailto:${email}?subject=${encodeURIComponent("72-Hour Sprint Intake — [Workflow Name]")}`;

const APPLY_URL =
  (import.meta as { env?: { VITE_HOSTED_APPLY_URL?: string } }).env
    ?.VITE_HOSTED_APPLY_URL || "";

const jobTypes = [
  "Lead intake → enrichment → CRM update → human handoff",
  "Browser-only admin workflow mapped into repeatable receipts",
  "Research pipeline with cited outputs and decision memo",
  "Inbox / form triage into an approval queue",
  "Data cleanup, matching, extraction, or report generation",
  "Automation audit: where the current workflow breaks and why",
  "Prototype for n8n, Make, Zapier, Airtable, Sheets, Slack, or CRM flows",
];

const proofItems = [
  "Run log with source inputs and decisions",
  "Screenshots or browser trace where useful",
  "Sample output a human can inspect",
  "Failure cases and boundary notes",
  "Handoff runbook and recommended next step",
  "Stop / narrow / sprint again / implement recommendation",
];

const boundaries = [
  "No vague ‘automate my business’ requests without a bounded workflow",
  "No spam, impersonation, phishing, fake reviews, credential theft, or market manipulation",
  "No irreversible production writes without human approval and rollback expectations",
  "No passwords, private keys, banking access, or broad admin credentials in the form",
  "No blind customer-facing sends, payments, refunds, trading, or financial movement",
  "No regulated-domain decisions without qualified human review",
  "No jobs whose success cannot be verified inside 72 hours",
];

const budgetOptions = [
  "$149 diagnostic only",
  "$500–$1,500 proof sprint",
  "$1,500+ implementation after proof",
  "Not sure — recommend the smallest safe step",
];

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function HostedApplyForm() {
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    name: "",
    email: "",
    company: "",
    use_case: "",
    telegram: "",
    notes: "",
    custody_ack: false,
  });

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    if (!form.custody_ack) {
      setError("You must acknowledge managed custody.");
      return;
    }
    setBusy(true);
    const payload = { ...form, sku: "elophanto-hosted" };
    try {
      localStorage.setItem(
        "elophanto.hosted.apply",
        JSON.stringify({ ...payload, ts: Date.now() })
      );
    } catch {
      /* ignore */
    }

    if (APPLY_URL) {
      try {
        const res = await fetch(APPLY_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(
            (body as { error?: string }).error || `Apply failed (${res.status})`
          );
        }
        setSubmitted(true);
        setBusy(false);
        return;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Submit failed");
        setBusy(false);
        return;
      }
    }

    const body = [
      `Name: ${form.name}`,
      `Email: ${form.email}`,
      `Company: ${form.company}`,
      `Use case: ${form.use_case}`,
      `Telegram: ${form.telegram}`,
      `Custody ack: yes (managed custody)`,
      `Notes: ${form.notes}`,
      "",
      "SKU: EloPhanto Hosted — please quote pricing",
    ].join("\n");
    window.location.href = `mailto:${email}?subject=${encodeURIComponent(
      "EloPhanto Hosted — apply"
    )}&body=${encodeURIComponent(body)}`;
    setSubmitted(true);
    setBusy(false);
  };

  if (submitted) {
    return (
      <div className="rounded-lg border border-primary/30 bg-primary/10 p-6">
        <h3 className="font-semibold">Application captured.</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          We’ll reply with fit, pricing, and next steps. Hosted is managed
          custody — nuclear is unavailable.
        </p>
      </div>
    );
  }

  return (
    <form className="grid gap-4 md:grid-cols-2" onSubmit={onSubmit}>
      <Input
        required
        placeholder="Your name"
        value={form.name}
        onChange={(e) => setForm({ ...form, name: e.target.value })}
      />
      <Input
        required
        type="email"
        placeholder="Email"
        value={form.email}
        onChange={(e) => setForm({ ...form, email: e.target.value })}
      />
      <Input
        placeholder="Company"
        value={form.company}
        onChange={(e) => setForm({ ...form, company: e.target.value })}
      />
      <Input
        placeholder="Telegram handle"
        value={form.telegram}
        onChange={(e) => setForm({ ...form, telegram: e.target.value })}
      />
      <Input
        className="md:col-span-2"
        required
        placeholder="What should the agent do for you?"
        value={form.use_case}
        onChange={(e) => setForm({ ...form, use_case: e.target.value })}
      />
      <textarea
        className="min-h-24 rounded-md border bg-background px-3 py-2 text-sm md:col-span-2"
        placeholder="Notes (optional)"
        value={form.notes}
        onChange={(e) => setForm({ ...form, notes: e.target.value })}
      />
      <label className="flex items-start gap-2 text-sm text-muted-foreground md:col-span-2">
        <input
          type="checkbox"
          className="mt-1"
          checked={form.custody_ack}
          onChange={(e) => setForm({ ...form, custody_ack: e.target.checked })}
          required
        />
        I understand Hosted is managed custody (not self-custody), nuclear is
        unavailable, and CRITICAL actions still require approval.
      </label>
      {error ? (
        <p className="text-sm text-destructive md:col-span-2">{error}</p>
      ) : null}
      <div className="md:col-span-2">
        <Button type="submit" size="lg" disabled={busy}>
          {busy ? "Submitting…" : "Apply for Hosted"} <ArrowRight />
        </Button>
      </div>
    </form>
  );
}

export function HirePage() {
  const [submitted, setSubmitted] = useState(false);

  return (
    <main className="min-h-screen bg-background text-foreground">
      <section className="border-b bg-gradient-to-b from-primary/10 via-background to-background">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-16 md:py-24">
          <Badge className="w-fit" variant="secondary">
            EloPhanto Hosted · Design partners
          </Badge>
          <div className="grid gap-10 lg:grid-cols-[1.2fr_0.8fr] lg:items-center">
            <div className="space-y-6">
              <h1 className="max-w-4xl text-4xl font-semibold tracking-tight md:text-6xl">
                Always-on agent. No Python. Laptop can sleep.
              </h1>
              <p className="max-w-2xl text-lg text-muted-foreground md:text-xl">
                EloPhanto Hosted is a managed box that runs your agent 24/7 with
                receipts and hard stop-points. Prefer the terminal? EloPhanto
                Open keeps the full CLI — clone the repo and run ./install.sh.
              </p>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button size="lg" onClick={() => scrollTo("apply-hosted")}>
                  Apply for a managed box <ArrowRight />
                </Button>
                <Button
                  size="lg"
                  variant="outline"
                  onClick={() => scrollTo("submit-job")}
                >
                  Or submit a 72h proof sprint
                </Button>
              </div>
              <p className="text-sm text-muted-foreground">
                Managed custody — labeled honestly. Nuclear mode is unavailable
                on Hosted.
              </p>
            </div>
            <Card className="border-primary/20 bg-card/80">
              <CardHeader>
                <CardTitle>Best fit</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 text-sm text-muted-foreground">
                <p>
                  <strong className="text-foreground">Hosted when:</strong> you
                  need lid-closed work, remote approvals, and a dedicated
                  browser — not another install on your Mac.
                </p>
                <p>
                  <strong className="text-foreground">Open when:</strong> you
                  want CLI, TUI, mind, and nuclear on your own machine.
                </p>
                <p>
                  <strong className="text-foreground">Sprint when:</strong> you
                  have one bounded workflow and need proof before buying a box
                  or engineering time.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      <section id="apply-hosted" className="scroll-mt-8 border-b bg-muted/20">
        <div className="mx-auto max-w-6xl px-6 py-14">
          <div className="mb-8 max-w-3xl">
            <h2 className="text-3xl font-semibold tracking-tight">
              Apply — EloPhanto Hosted
            </h2>
            <p className="mt-3 text-muted-foreground">
              Tell us what you need. We’ll reply with fit, pricing, and how we
              provision your box. Open stays free under PolyForm NC.
            </p>
          </div>
          <Card>
            <CardContent className="pt-6">
              <HostedApplyForm />
            </CardContent>
          </Card>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-14">
        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Proof sprint</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-muted-foreground">
              <p>
                Best when the workflow is real but unproven. Sample data,
                staging, browser traces, or scoped access for inspectable proof.
              </p>
              <Button variant="outline" onClick={() => scrollTo("submit-job")}>
                Scope a proof sprint
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Implementation after proof</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-muted-foreground">
              <p>
                Best after the sprint proves value and you want production
                hardening with explicit milestones and risk controls.
              </p>
              <Button variant="outline" onClick={() => scrollTo("submit-job")}>
                Start with scope review
              </Button>
            </CardContent>
          </Card>
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl gap-8 px-6 py-10 lg:grid-cols-[0.9fr_1.1fr]">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight">
            What jobs fit the sprint?
          </h2>
          <p className="mt-3 text-muted-foreground">
            Concrete input, useful output, safe test path, inspectable proof.
          </p>
        </div>
        <div className="grid gap-3">
          {jobTypes.map((job) => (
            <div
              key={job}
              className="flex gap-3 rounded-lg border bg-card p-4 text-sm"
            >
              <CheckCircle2 className="mt-0.5 size-4 text-primary" />
              {job}
            </div>
          ))}
        </div>
      </section>

      <section className="border-y bg-muted/30">
        <div className="mx-auto max-w-6xl px-6 py-14">
          <h2 className="text-3xl font-semibold tracking-tight">
            What you receive after 72 hours
          </h2>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {proofItems.map((item) => (
              <Card key={item}>
                <CardContent className="pt-6 text-sm text-muted-foreground">
                  {item}
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-14">
        <div className="grid gap-8 lg:grid-cols-3">
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle>Pricing and scoping</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p>
                <strong className="text-foreground">Hosted</strong> — managed
                always-on box; pricing confirmed when you apply.
              </p>
              <p>
                <strong className="text-foreground">$149 diagnostic</strong> for
                process map and go/no-go.
              </p>
              <p>
                <strong className="text-foreground">$500–$1,500 proof sprint</strong>{" "}
                for a bounded 72-hour package.
              </p>
              <Button onClick={() => scrollTo("submit-job")}>
                Submit before payment
              </Button>
            </CardContent>
          </Card>
          <div className="grid gap-4 lg:col-span-2 md:grid-cols-2">
            {[
              "Submit one workflow",
              "I review fit before payment",
              "We agree on the proof target",
              "I run the safe slice",
              "You receive the closeout package",
            ].map((step, index) => (
              <Card key={step}>
                <CardContent className="flex gap-3 pt-6 text-sm">
                  <Clock3 className="size-4 text-primary" />
                  <span>
                    <strong>
                      {index + 1}. {step}
                    </strong>
                    <br />
                    <span className="text-muted-foreground">
                      Risky actions use sample data, staging, scoped access, or
                      human approval gates.
                    </span>
                  </span>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y bg-muted/30">
        <div className="mx-auto grid max-w-6xl gap-8 px-6 py-14 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <h2 className="text-3xl font-semibold tracking-tight">
              What I will not run
            </h2>
            <p className="mt-3 text-muted-foreground">
              Bounded, inspectable proof — not unsafe autonomy.
            </p>
          </div>
          <div className="space-y-3">
            {boundaries.map((item) => (
              <div
                key={item}
                className="rounded-lg border bg-background p-4 text-sm text-muted-foreground"
              >
                <ShieldCheck className="mr-2 inline size-4 text-primary" />
                {item}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="submit-job" className="scroll-mt-8 border-t bg-primary/5">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-8 max-w-3xl">
            <h2 className="text-3xl font-semibold tracking-tight">
              Submit a workflow for scope review
            </h2>
            <p className="mt-3 text-muted-foreground">
              One bounded workflow. Fit and risk review before payment.
            </p>
          </div>
          <Card>
            <CardContent className="pt-6">
              {submitted ? (
                <div className="rounded-lg border border-primary/30 bg-primary/10 p-6">
                  <h3 className="font-semibold">Workflow received.</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Review before payment. No secrets in the form.
                  </p>
                </div>
              ) : (
                <form
                  className="grid gap-4 md:grid-cols-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    setSubmitted(true);
                    window.location.href = mailto;
                  }}
                >
                  <Input required placeholder="Contact name" />
                  <Input required type="email" placeholder="Contact email" />
                  <Input required placeholder="Workflow title" />
                  <Input required placeholder="Desired job outcome" />
                  <textarea
                    required
                    className="min-h-28 rounded-md border bg-background px-3 py-2 text-sm md:col-span-2"
                    placeholder="Current manual process"
                  />
                  <select
                    className="rounded-md border bg-background px-3 py-2 text-sm md:col-span-2"
                    defaultValue=""
                  >
                    <option value="" disabled>
                      Budget band
                    </option>
                    {budgetOptions.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                  <div className="md:col-span-2 flex flex-wrap gap-3">
                    <Button type="submit">
                      Submit sprint intake <ArrowRight />
                    </Button>
                    <Button type="button" variant="outline" asChild>
                      <a href={mailto}>
                        <Mail /> Email instead
                      </a>
                    </Button>
                  </div>
                </form>
              )}
            </CardContent>
          </Card>
        </div>
      </section>
    </main>
  );
}
