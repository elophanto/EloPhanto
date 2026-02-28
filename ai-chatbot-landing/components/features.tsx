import { Brain, Zap, Shield, Globe } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

const features = [
  {
    icon: Brain,
    title: "Contextual Memory",
    description:
      "Aura remembers your previous conversations and preferences, making every interaction smarter and more personal.",
  },
  {
    icon: Zap,
    title: "Instant Responses",
    description:
      "Get answers in milliseconds, not minutes. Our optimized architecture ensures you never wait for the help you need.",
  },
  {
    icon: Shield,
    title: "Private & Secure",
    description:
      "Your conversations stay yours. End-to-end encryption and zero data retention keep your information safe.",
  },
  {
    icon: Globe,
    title: "Works Everywhere",
    description:
      "Access Aura from any device, in any language. Seamless experience across web, mobile, and desktop apps.",
  },
];

export function Features() {
  return (
    <section id="features" className="scroll-mt-16 py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        {/* Section header */}
        <div className="mx-auto mb-16 max-w-2xl text-center">
          <p className="mb-3 text-sm font-medium uppercase tracking-wider text-primary">
            Features
          </p>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Everything you need, nothing you don&apos;t
          </h2>
          <p className="mt-4 text-muted-foreground">
            Built from the ground up to be the AI assistant you&apos;ve always wanted.
          </p>
        </div>

        {/* Feature grid */}
        <div className="grid gap-6 sm:grid-cols-2">
          {features.map((feature) => (
            <Card
              key={feature.title}
              className="group border-border/50 bg-card/50 backdrop-blur-sm hover:border-primary/20 hover:bg-card"
            >
              <CardHeader>
                <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                  <feature.icon className="h-5 w-5" />
                </div>
                <CardTitle className="text-xl">{feature.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base leading-relaxed">
                  {feature.description}
                </CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
