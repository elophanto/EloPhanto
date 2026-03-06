import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

export const metadata: Metadata = {
  title: "About Us | Polo Tourism in Sotogrande, Spain",
  description:
    "Learn about Sotogrande Polo Tourism — our partnership model, our team, and why Sotogrande is Europe's premier polo destination. Tourism-first approach with transparent pricing.",
  keywords: [
    "sotogrande polo",
    "polo tourism spain",
    "polo valley partnership",
    "santa maria polo club",
    "equestrian tourism andalucia",
  ],
  alternates: {
    canonical: "https://sotograndepolo.com/about",
  },
};

export default function AboutPage() {
  return (
    <>
      {/* Hero */}
      <section className="relative h-[45vh] min-h-[350px] flex items-end">
        <Image
          src="https://images.unsplash.com/photo-1558618666-fcd25c85f82e?w=1920&q=80"
          alt="Polo field in Sotogrande, Andalusia with players"
          fill
          className="object-cover"
          priority
          sizes="100vw"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-navy/80 via-navy/30 to-transparent" />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-12 w-full">
          <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
            About Us
          </p>
          <h1
            className="text-3xl sm:text-4xl lg:text-5xl font-bold text-white"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            Our Story
          </h1>
        </div>
      </section>

      {/* Mission */}
      <section className="py-16 lg:py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            <div>
              <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
                Our Mission
              </p>
              <h2
                className="text-2xl sm:text-3xl font-bold text-navy mb-4"
                style={{ fontFamily: "var(--font-playfair), serif" }}
              >
                Making Polo Accessible to Everyone
              </h2>
              <div className="space-y-4 text-navy/70 leading-relaxed">
                <p>
                  Polo has long been called the &ldquo;Sport of Kings&rdquo; — but we believe
                  it should be the sport of everyone. Sotogrande Polo Tourism was
                  founded with a simple idea: bring the thrill of polo to tourists,
                  travellers, and curious beginners, without the traditional barriers
                  of horse ownership or club membership.
                </p>
                <p>
                  Based in Sotogrande, Andalusia — one of Europe&apos;s most prestigious
                  polo regions — we partner with world-class polo clubs to deliver
                  complete tourism experiences. From a two-hour discovery session to a
                  five-day immersion, every package is designed for people who have
                  never touched a mallet.
                </p>
                <p>
                  Our tourism-first approach means everything is taken care of:
                  equipment, instruction, meals, photos, and even accommodation. You
                  just show up and enjoy.
                </p>
              </div>
            </div>
            <div className="relative h-80 lg:h-[400px] rounded-xl overflow-hidden">
              <Image
                src="https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=900&q=80"
                alt="Luxury resort in Sotogrande, Andalusia"
                fill
                className="object-cover"
                sizes="(max-width: 1024px) 100vw, 50vw"
              />
            </div>
          </div>
        </div>
      </section>

      {/* Partnership Model */}
      <section className="py-16 lg:py-24 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
              Our Model
            </p>
            <h2
              className="text-2xl sm:text-3xl font-bold text-navy mb-4"
              style={{ fontFamily: "var(--font-playfair), serif" }}
            >
              The Partnership Approach
            </h2>
            <p className="text-navy/60 leading-relaxed">
              Instead of owning horses, stables, and facilities, we partner with
              Sotogrande&apos;s established polo clubs. This means lower costs for you
              and premium facilities guaranteed.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Traditional */}
            <div className="border border-cream-dark rounded-xl p-8 bg-cream/30">
              <h3 className="text-lg font-bold text-navy/40 mb-4 line-through">
                Traditional Polo Business
              </h3>
              <ul className="space-y-3 text-sm text-navy/50">
                {[
                  "Own horses and stables (€50,000+ investment)",
                  "Hire and manage instructors",
                  "Maintain facilities year-round",
                  "High overhead, low margins (30–40%)",
                  "Opaque pricing — 'contact for a quote'",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2">
                    <svg className="w-4 h-4 text-red-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
            {/* Our model */}
            <div className="border-2 border-gold rounded-xl p-8 bg-gold/5">
              <h3 className="text-lg font-bold text-navy mb-4">
                Our Partnership Model
              </h3>
              <ul className="space-y-3 text-sm text-navy/70">
                {[
                  "Partner with Polo Valley & Santa Maria Polo Club",
                  "Use their world-class horses, facilities & instructors",
                  "Focus on marketing, booking & customer experience",
                  "Lower cost = lower prices for our guests",
                  "Transparent pricing — every price on our website",
                ].map((item) => (
                  <li key={item} className="flex items-start gap-2">
                    <svg className="w-4 h-4 text-green shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Partners */}
      <section className="py-16 lg:py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
              Our Partners
            </p>
            <h2
              className="text-2xl sm:text-3xl font-bold text-navy mb-4"
              style={{ fontFamily: "var(--font-playfair), serif" }}
            >
              World-Class Polo Facilities
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="bg-white border border-cream-dark rounded-xl p-8">
              <div className="w-16 h-16 bg-navy/10 rounded-full flex items-center justify-center mb-4">
                <span className="text-navy font-bold text-lg">PV</span>
              </div>
              <h3 className="text-xl font-bold text-navy mb-2">Polo Valley</h3>
              <p className="text-gold text-sm font-semibold mb-3">
                &ldquo;The #1 Polo Club to Learn &amp; Play Polo&rdquo;
              </p>
              <p className="text-navy/70 text-sm leading-relaxed">
                Our primary facility partner. Polo Valley is renowned for its
                learner-focused approach, professional instructors, and beautiful
                grounds in the Málaga Valley near Sotogrande. All beginner and
                intermediate sessions take place here.
              </p>
            </div>
            <div className="bg-white border border-cream-dark rounded-xl p-8">
              <div className="w-16 h-16 bg-navy/10 rounded-full flex items-center justify-center mb-4">
                <span className="text-navy font-bold text-lg">SM</span>
              </div>
              <h3 className="text-xl font-bold text-navy mb-2">
                Santa Maria Polo Club
              </h3>
              <p className="text-gold text-sm font-semibold mb-3">
                49th International Tournament Season
              </p>
              <p className="text-navy/70 text-sm leading-relaxed">
                One of Europe&apos;s most prestigious polo clubs, home to the famous
                International Tournament. During peak season (July–August), our Week
                Immersion guests enjoy exclusive match-watching experiences here.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Why Sotogrande */}
      <section className="py-16 lg:py-24 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            <div className="relative h-80 lg:h-[400px] rounded-xl overflow-hidden order-2 lg:order-1">
              <Image
                src="https://images.unsplash.com/photo-1509042239860-f550ce710b93?w=900&q=80"
                alt="Sunny Andalusian coastline near Sotogrande"
                fill
                className="object-cover"
                sizes="(max-width: 1024px) 100vw, 50vw"
              />
            </div>
            <div className="order-1 lg:order-2">
              <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
                The Destination
              </p>
              <h2
                className="text-2xl sm:text-3xl font-bold text-navy mb-4"
                style={{ fontFamily: "var(--font-playfair), serif" }}
              >
                Why Sotogrande?
              </h2>
              <div className="space-y-4 text-navy/70 leading-relaxed text-sm">
                <p>
                  Sotogrande sits on Andalusia&apos;s Costa de la Luz — Spain&apos;s stunning
                  southern coastline. It&apos;s one of Europe&apos;s most exclusive
                  residential and leisure destinations, famous for polo, golf, and
                  Mediterranean living.
                </p>
              </div>
              <ul className="mt-6 space-y-3 text-sm text-navy/70">
                {[
                  { label: "Location", value: "Costa de la Luz, Andalusia, Spain" },
                  { label: "Climate", value: "300+ days of sunshine, mild winters" },
                  { label: "Nearest Airport", value: "Gibraltar (20 min), Málaga (90 min)" },
                  { label: "Nearby", value: "Marbella, Tarifa, Gibraltar" },
                  { label: "Polo Season", value: "Year-round (peak: July–August)" },
                ].map((item) => (
                  <li key={item.label} className="flex items-start gap-3">
                    <span className="text-gold font-semibold whitespace-nowrap min-w-[120px]">
                      {item.label}
                    </span>
                    <span>{item.value}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Team */}
      <section className="py-16 lg:py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
            Our Team
          </p>
          <h2
            className="text-2xl sm:text-3xl font-bold text-navy mb-10"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            Meet the People Behind the Experiences
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-8 max-w-3xl mx-auto">
            {[
              {
                name: "Founder & Director",
                role: "Operations & partnerships",
              },
              {
                name: "Head Instructor",
                role: "Polo Valley",
              },
              {
                name: "Guest Experience Manager",
                role: "Bookings & hospitality",
              },
            ].map((member) => (
              <div key={member.name}>
                <div className="w-24 h-24 bg-cream-dark rounded-full mx-auto mb-4 flex items-center justify-center">
                  <svg className="w-10 h-10 text-navy/20" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
                  </svg>
                </div>
                <h3 className="font-bold text-navy text-sm">{member.name}</h3>
                <p className="text-navy/50 text-xs">{member.role}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-16 lg:py-20 bg-navy text-white text-center">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2
            className="text-2xl sm:text-3xl font-bold mb-4"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            Experience It For Yourself
          </h2>
          <p className="text-white/70 mb-8">
            Whether you&apos;re a curious traveller or planning a corporate event,
            we&apos;d love to welcome you to the world of polo.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link
              href="/packages"
              className="inline-flex items-center justify-center px-7 py-3.5 bg-gold hover:bg-gold-dark text-white font-semibold rounded-lg transition-colors text-sm"
            >
              View Packages
            </Link>
            <Link
              href="/contact"
              className="inline-flex items-center justify-center px-7 py-3.5 bg-white/10 hover:bg-white/20 text-white font-semibold rounded-lg transition-colors text-sm border border-white/20"
            >
              Get in Touch
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
