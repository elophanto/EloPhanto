import { Star } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

const testimonials = [
  {
    name: "Sarah Chen",
    role: "Product Designer",
    content:
      "Aura has completely changed how I brainstorm. It's like having a brilliant coworker who's always available and never judges your rough ideas.",
    rating: 5,
  },
  {
    name: "Marcus Rivera",
    role: "Software Engineer",
    content:
      "I've tried every AI chatbot out there. Aura is the first one that actually remembers context across conversations. Game changer for complex projects.",
    rating: 5,
  },
  {
    name: "Emily Nakamura",
    role: "Startup Founder",
    content:
      "We replaced three different tools with Aura. It handles customer research, content drafting, and data analysis — all in one conversation.",
    rating: 5,
  },
];

export function Testimonials() {
  return (
    <section id="testimonials" className="scroll-mt-16 py-20 sm:py-28">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        {/* Section header */}
        <div className="mx-auto mb-16 max-w-2xl text-center">
          <p className="mb-3 text-sm font-medium uppercase tracking-wider text-primary">
            Testimonials
          </p>
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Loved by thousands
          </h2>
          <p className="mt-4 text-muted-foreground">
            Don&apos;t just take our word for it.
          </p>
        </div>

        {/* Testimonial cards */}
        <div className="grid gap-6 md:grid-cols-3">
          {testimonials.map((testimonial) => (
            <Card
              key={testimonial.name}
              className="border-border/50 bg-card/50 backdrop-blur-sm hover:border-primary/20"
            >
              <CardContent className="p-6">
                {/* Stars */}
                <div className="mb-4 flex gap-0.5">
                  {Array.from({ length: testimonial.rating }).map((_, i) => (
                    <Star
                      key={i}
                      className="h-4 w-4 fill-amber-400 text-amber-400"
                    />
                  ))}
                </div>

                {/* Quote */}
                <p className="mb-6 text-sm leading-relaxed text-muted-foreground">
                  &ldquo;{testimonial.content}&rdquo;
                </p>

                {/* Author */}
                <div className="flex items-center gap-3">
                  <div
                    className="flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold text-white"
                    style={{
                      background: `hsl(173, 50%, ${35 + testimonials.indexOf(testimonial) * 8}%)`,
                    }}
                  >
                    {testimonial.name
                      .split(" ")
                      .map((n) => n[0])
                      .join("")}
                  </div>
                  <div>
                    <p className="text-sm font-medium">{testimonial.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {testimonial.role}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
