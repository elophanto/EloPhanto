import { MessageCircle, Cpu, CheckCircle2 } from "lucide-react";

const steps = [
  {
    icon: MessageCircle,
    step: "01",
    title: "Ask anything",
    description:
      "Type your question naturally — just like talking to a friend. No special syntax or commands needed.",
  },
  {
    icon: Cpu,
    step: "02",
    title: "Aura thinks",
    description:
      "Our AI processes your request with deep context understanding, pulling from vast knowledge to craft the perfect response.",
  },
  {
    icon: CheckCircle2,
    step: "03",
    title: "Get results",
    description:
      "Receive clear, actionable answers in seconds. Follow up to refine — Aura keeps the full context of your conversation.",
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-16 border-y border-border/50 bg-muted/30 py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        {/* Section header */}
        <div className="mx-auto mb-16 max-w-2xl text-center">
          <p className="mb-3 text-sm font-medium uppercase tracking-wider text-primary">
            How it Works
          </p>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Simple by design
          </h2>
          <p className="mt-4 text-muted-foreground">
            Three steps. That&apos;s all it takes.
          </p>
        </div>

        {/* Steps */}
        <div className="grid gap-8 md:grid-cols-3 md:gap-12">
          {steps.map((step, index) => (
            <div key={step.step} className="group relative text-center">
              {/* Connector line (desktop) */}
              {index < steps.length - 1 && (
                <div className="absolute left-[calc(50%+40px)] top-10 hidden h-px w-[calc(100%-80px)] bg-border md:block" />
              )}

              <div className="relative mx-auto mb-6 flex h-20 w-20 items-center justify-center">
                {/* Circle background */}
                <div className="absolute inset-0 rounded-full border-2 border-border bg-background transition-colors group-hover:border-primary/30" />
                <step.icon className="relative h-8 w-8 text-primary" />
              </div>

              <span className="mb-2 block text-xs font-bold uppercase tracking-widest text-primary/60">
                Step {step.step}
              </span>
              <h3 className="mb-3 text-xl font-semibold">{step.title}</h3>
              <p className="mx-auto max-w-xs text-sm leading-relaxed text-muted-foreground">
                {step.description}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
