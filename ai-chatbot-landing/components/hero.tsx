import { ArrowRight, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Hero() {
  return (
    <section className="relative overflow-hidden pt-16">
      {/* Subtle gradient orbs */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 right-0 h-[500px] w-[500px] rounded-full bg-primary/5 blur-3xl" />
        <div className="absolute -bottom-20 -left-20 h-[400px] w-[400px] rounded-full bg-primary/5 blur-3xl" />
      </div>

      <div className="relative mx-auto flex max-w-6xl flex-col items-center px-4 pb-20 pt-24 text-center sm:px-6 sm:pb-28 sm:pt-32">
        {/* Badge */}
        <div className="animate-fade-in mb-6 inline-flex items-center gap-2 rounded-full border border-border bg-secondary px-4 py-1.5 text-sm text-secondary-foreground">
          <Sparkles className="h-3.5 w-3.5" />
          <span>Now powered by next-gen AI</span>
        </div>

        {/* Headline */}
        <h1 className="animate-fade-in-up max-w-3xl text-4xl font-bold leading-tight tracking-tight sm:text-5xl md:text-6xl lg:text-7xl">
          Conversations that{" "}
          <span className="bg-gradient-to-r from-primary to-emerald-500 bg-clip-text text-transparent">
            feel human
          </span>
        </h1>

        {/* Subheadline */}
        <p className="animate-fade-in-up-delay mt-6 max-w-xl text-base text-muted-foreground sm:text-lg md:text-xl opacity-0">
          Meet Aura — an AI assistant that understands context, remembers your
          preferences, and delivers answers that actually help.
        </p>

        {/* CTAs */}
        <div className="animate-fade-in-up-delay mt-10 flex flex-col gap-3 opacity-0 sm:flex-row sm:gap-4">
          <Button size="lg" className="gap-2">
            Start chatting free
            <ArrowRight className="h-4 w-4" />
          </Button>
          <Button size="lg" variant="outline" className="gap-2">
            See it in action
          </Button>
        </div>

        {/* Social proof bar */}
        <div className="animate-fade-in mt-16 flex flex-col items-center gap-4 opacity-0 sm:flex-row sm:gap-8">
          <div className="flex -space-x-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div
                key={i}
                className="h-8 w-8 rounded-full border-2 border-background bg-muted"
                style={{
                  background: `hsl(${170 + i * 15}, 40%, ${55 + i * 5}%)`,
                }}
              />
            ))}
          </div>
          <div className="text-sm text-muted-foreground">
            <span className="font-semibold text-foreground">10,000+</span>{" "}
            people are already chatting
          </div>
        </div>
      </div>
    </section>
  );
}
