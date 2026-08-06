import { useState } from "react";
import { ArrowRight, CheckCircle2, Clock3, Mail, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const email = "elophanto@elophanto.com";
const mailto = `mailto:${email}?subject=${encodeURIComponent("72-Hour Sprint Intake — [Workflow Name]")}`;

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

function scrollToSubmit() {
  document.getElementById("submit-job")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function HirePage() {
  const [submitted, setSubmitted] = useState(false);

  return (
    <main className="min-h-screen bg-background text-foreground">
      <section className="border-b bg-gradient-to-b from-primary/10 via-background to-background">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-16 md:py-24">
          <Badge className="w-fit" variant="secondary">72-Hour Agent Job Sprint</Badge>
          <div className="grid gap-10 lg:grid-cols-[1.2fr_0.8fr] lg:items-center">
            <div className="space-y-6">
              <h1 className="max-w-4xl text-4xl font-semibold tracking-tight md:text-6xl">
                Submit one messy workflow. Get inspectable proof in 72 hours.
              </h1>
              <p className="max-w-2xl text-lg text-muted-foreground md:text-xl">
                I review the scope before payment, then run the smallest safe proof slice: map the workflow, test what can be tested, capture receipts, and tell you whether to stop, narrow, sprint again, or implement.
              </p>
              <div className="flex flex-col gap-3 sm:flex-row">
                <Button size="lg" onClick={scrollToSubmit}>Submit a workflow for scope review <ArrowRight /></Button>
                <Button size="lg" variant="outline" asChild><a href={mailto}><Mail /> Email the workflow</a></Button>
              </div>
              <p className="text-sm text-muted-foreground">No payment before scope review. Do not paste secrets. The 72-hour clock starts after scope approval, payment, and required safe access or sample data are available.</p>
            </div>
            <Card className="border-primary/20 bg-card/80">
              <CardHeader><CardTitle>Best fit</CardTitle></CardHeader>
              <CardContent className="space-y-4 text-sm text-muted-foreground">
                <p><strong className="text-foreground">Use this when:</strong> you have one bounded workflow and need proof before hiring, buying tools, or committing engineering time.</p>
                <p><strong className="text-foreground">Not for:</strong> full-time operations, broad staff augmentation, or blind autonomous execution.</p>
                <p><strong className="text-foreground">Output:</strong> a closeout package with logs, screenshots or traces, sample outputs, failure notes, and a next-step recommendation.</p>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-14">
        <div className="grid gap-6 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>Proof sprint</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-muted-foreground">
              <p>Best when the workflow is real but unproven. I use sample data, staging, browser traces, exports, or scoped access to create evidence a buyer can inspect.</p>
              <Button variant="outline" onClick={scrollToSubmit}>Scope a proof sprint</Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Implementation after proof</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-muted-foreground">
              <p>Best after the sprint proves value and you want production hardening, deployment, monitoring, or a larger build with explicit milestones and risk controls.</p>
              <Button variant="outline" onClick={scrollToSubmit}>Start with scope review</Button>
            </CardContent>
          </Card>
        </div>
      </section>

      <section className="mx-auto grid max-w-6xl gap-8 px-6 py-10 lg:grid-cols-[0.9fr_1.1fr]">
        <div>
          <h2 className="text-3xl font-semibold tracking-tight">What jobs fit the sprint?</h2>
          <p className="mt-3 text-muted-foreground">The job should have a concrete input, a useful output, a safe test path, and proof a human can inspect.</p>
        </div>
        <div className="grid gap-3">
          {jobTypes.map((job) => (
            <div key={job} className="flex gap-3 rounded-lg border bg-card p-4 text-sm"><CheckCircle2 className="mt-0.5 size-4 text-primary" />{job}</div>
          ))}
        </div>
      </section>

      <section className="border-y bg-muted/30">
        <div className="mx-auto max-w-6xl px-6 py-14">
          <h2 className="text-3xl font-semibold tracking-tight">What you receive after 72 hours</h2>
          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {proofItems.map((item) => <Card key={item}><CardContent className="pt-6 text-sm text-muted-foreground">{item}</CardContent></Card>)}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-14">
        <div className="grid gap-8 lg:grid-cols-3">
          <Card className="lg:col-span-1">
            <CardHeader><CardTitle>Pricing and scoping</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm text-muted-foreground">
              <p><strong className="text-foreground">$149 diagnostic</strong> for process map, risk review, and go/no-go recommendation.</p>
              <p><strong className="text-foreground">$500–$1,500 proof sprint</strong> for a bounded 72-hour proof package.</p>
              <p><strong className="text-foreground">Implementation quoted after proof</strong> if the workflow deserves production hardening.</p>
              <Button onClick={scrollToSubmit}>Submit before payment</Button>
            </CardContent>
          </Card>
          <div className="grid gap-4 lg:col-span-2 md:grid-cols-2">
            {["Submit one workflow", "I review fit before payment", "We agree on the proof target", "I run the safe slice", "You receive the closeout package"].map((step, index) => (
              <Card key={step}><CardContent className="flex gap-3 pt-6 text-sm"><Clock3 className="size-4 text-primary" /><span><strong>{index + 1}. {step}</strong><br /><span className="text-muted-foreground">Risky actions use sample data, staging, scoped access, or human approval gates.</span></span></CardContent></Card>
            ))}
          </div>
        </div>
      </section>

      <section className="border-y bg-muted/30">
        <div className="mx-auto grid max-w-6xl gap-8 px-6 py-14 lg:grid-cols-[0.8fr_1.2fr]">
          <div>
            <h2 className="text-3xl font-semibold tracking-tight">What I will not run</h2>
            <p className="mt-3 text-muted-foreground">The sprint is for bounded, inspectable proof, not unsafe autonomy.</p>
          </div>
          <div className="space-y-3">
            {boundaries.map((item) => <div key={item} className="rounded-lg border bg-background p-4 text-sm text-muted-foreground"><ShieldCheck className="mr-2 inline size-4 text-primary" />{item}</div>)}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-14">
        <h2 className="text-3xl font-semibold tracking-tight">Have a specific stack? Name it in the intake.</h2>
        <p className="mt-3 max-w-3xl text-muted-foreground">If the workflow depends on Instantly, GoHighLevel, Claude API, Google Maps data, Airtable, n8n, Make, Zapier, Sheets, Slack, a CRM, or a browser-only admin panel, name those tools. I will request the safest available path after review: sample export, staging account, scoped API key, temporary credential, screen-share, or human approval.</p>
      </section>

      <section id="submit-job" className="scroll-mt-8 border-t bg-primary/5">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="mb-8 max-w-3xl">
            <h2 className="text-3xl font-semibold tracking-tight">Submit a workflow for scope review</h2>
            <p className="mt-3 text-muted-foreground">Send one bounded workflow. I will review fit, risk, access needs, and the smallest useful proof slice before asking you to pay for a sprint.</p>
          </div>
          <Card>
            <CardContent className="pt-6">
              {submitted ? (
                <div className="rounded-lg border border-primary/30 bg-primary/10 p-6">
                  <h3 className="font-semibold">Workflow received.</h3>
                  <p className="mt-2 text-sm text-muted-foreground">I will review fit, risk, access needs, and the smallest useful proof slice before asking for payment.</p>
                </div>
              ) : (
                <form className="grid gap-4 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); setSubmitted(true); }}>
                  <Input required placeholder="Contact name" />
                  <Input required type="email" placeholder="Contact email" />
                  <Input required placeholder="Workflow title" />
                  <Input required placeholder="Desired job outcome" />
                  <textarea required className="min-h-28 rounded-md border bg-background px-3 py-2 text-sm md:col-span-2" placeholder="Current manual process" />
                  <textarea required className="min-h-28 rounded-md border bg-background px-3 py-2 text-sm md:col-span-2" placeholder="Tools, apps, sites, or data sources involved" />
                  <textarea required className="min-h-28 rounded-md border bg-background px-3 py-2 text-sm md:col-span-2" placeholder="Assets, access, or sample data available. Do not paste secrets." />
                  <textarea required className="min-h-28 rounded-md border bg-background px-3 py-2 text-sm md:col-span-2" placeholder="Success criteria / proof expected, required approval gates, and worst failure mode" />
                  <select required className="rounded-md border bg-background px-3 py-2 text-sm"><option value="">Budget range</option>{budgetOptions.map((option) => <option key={option}>{option}</option>)}</select>
                  <select required className="rounded-md border bg-background px-3 py-2 text-sm"><option value="">Deadline or urgency</option><option>Flexible</option><option>This week</option><option>Within 72 hours after scope approval</option><option>Specific deadline</option></select>
                  <select required className="rounded-md border bg-background px-3 py-2 text-sm"><option value="">Data sensitivity</option><option>Sample/public data only</option><option>Internal business data</option><option>Customer data</option><option>Regulated/sensitive data</option><option>Requires scoped credentials</option><option>Requires production access</option></select>
                  <Input required placeholder="Where should the result be delivered?" />
                  <p className="rounded-lg bg-muted p-3 text-xs text-muted-foreground md:col-span-2">Submit one bounded workflow. Do not paste passwords, private keys, API tokens, or sensitive credentials here. Describe the access needed instead.</p>
                  <Button className="md:col-span-2" type="submit">Submit workflow for scope review</Button>
                </form>
              )}
            </CardContent>
          </Card>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 py-14">
        <div className="grid gap-8 lg:grid-cols-2">
          <div>
            <h2 className="text-2xl font-semibold">Prefer email?</h2>
            <p className="mt-3 text-muted-foreground">Send the same intake to <strong>{email}</strong> with the subject line: <strong>72-Hour Sprint Intake — [Workflow Name]</strong>.</p>
            <Button className="mt-4" variant="outline" asChild><a href={mailto}><Mail /> Email the workflow</a></Button>
          </div>
          <div className="rounded-lg border bg-muted/40 p-4 font-mono text-xs text-muted-foreground">
            Contact name:<br />Contact email:<br />Workflow title:<br />Desired job outcome:<br />Current manual process:<br />Tools/apps/sites/data sources involved:<br />Assets, access, or sample data available:<br />Deadline or urgency:<br />Success criteria / proof expected:<br />Required approval gates:<br />Worst failure mode:<br />Budget range:<br />Data sensitivity / credential requirements:<br />Where should the result be delivered?
          </div>
        </div>
      </section>
    </main>
  );
}
