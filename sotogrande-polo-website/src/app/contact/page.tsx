import type { Metadata } from "next";
import ContactForm from "@/components/ContactForm";
import FAQ from "@/components/FAQ";
import { faqs } from "@/lib/data";

export const metadata: Metadata = {
  title: "Contact Us | Book Your Polo Experience",
  description:
    "Get in touch with Sotogrande Polo Tourism. Book your polo experience, ask questions, or plan a corporate event. Based in Sotogrande, Andalusia, Spain.",
  keywords: [
    "contact sotogrande polo",
    "book polo experience",
    "polo inquiry spain",
    "corporate polo events contact",
  ],
  alternates: {
    canonical: "https://sotograndepolo.com/contact",
  },
};

export default function ContactPage() {
  return (
    <>
      {/* Hero */}
      <section className="bg-navy text-white py-20 lg:py-28">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
            Get in Touch
          </p>
          <h1
            className="text-4xl sm:text-5xl font-bold mb-4"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            Contact Us
          </h1>
          <p className="text-white/70 text-lg max-w-2xl mx-auto leading-relaxed">
            Ready to book your polo experience? Have questions about our packages?
            We&apos;d love to hear from you. We respond within 24 hours.
          </p>
        </div>
      </section>

      {/* Contact Form + Info */}
      <section className="py-16 lg:py-24">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
            {/* Form */}
            <div className="lg:col-span-2">
              <h2 className="text-xl font-bold text-navy mb-6">Send Us a Message</h2>
              <ContactForm />
            </div>

            {/* Sidebar */}
            <div className="space-y-6">
              {/* Contact info */}
              <div className="bg-white border border-cream-dark rounded-xl p-6">
                <h3 className="font-bold text-navy mb-4">Contact Information</h3>
                <ul className="space-y-4 text-sm">
                  <li className="flex items-start gap-3">
                    <svg className="w-5 h-5 text-gold shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                    </svg>
                    <div>
                      <p className="text-navy/50 text-xs mb-0.5">Email</p>
                      <p className="text-navy font-medium">info@sotograndepolo.com</p>
                    </div>
                  </li>
                  <li className="flex items-start gap-3">
                    <svg className="w-5 h-5 text-gold shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
                    </svg>
                    <div>
                      <p className="text-navy/50 text-xs mb-0.5">Phone</p>
                      <p className="text-navy font-medium">+34 XXX XXX XXX</p>
                    </div>
                  </li>
                  <li className="flex items-start gap-3">
                    <svg className="w-5 h-5 text-gold shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    <div>
                      <p className="text-navy/50 text-xs mb-0.5">Location</p>
                      <p className="text-navy font-medium">Sotogrande, Andalusia, Spain</p>
                    </div>
                  </li>
                </ul>
              </div>

              {/* Response time */}
              <div className="bg-gold/5 border border-gold/20 rounded-xl p-6">
                <h3 className="font-bold text-navy mb-2">Quick Response</h3>
                <p className="text-navy/70 text-sm leading-relaxed">
                  We respond to all inquiries within 24 hours. For corporate
                  events, we&apos;ll send a custom quote tailored to your group size
                  and preferences.
                </p>
              </div>

              {/* Social */}
              <div className="bg-white border border-cream-dark rounded-xl p-6">
                <h3 className="font-bold text-navy mb-4">Follow Us</h3>
                <div className="flex gap-3">
                  {[
                    { name: "Instagram", abbr: "IG" },
                    { name: "Facebook", abbr: "FB" },
                    { name: "YouTube", abbr: "YT" },
                  ].map((platform) => (
                    <a
                      key={platform.name}
                      href="#"
                      aria-label={platform.name}
                      className="w-10 h-10 rounded-full bg-navy/5 hover:bg-gold/10 flex items-center justify-center text-navy/60 hover:text-gold text-xs font-bold transition-colors"
                    >
                      {platform.abbr}
                    </a>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Map placeholder */}
      <section className="bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
          <div className="bg-cream-dark rounded-xl h-64 lg:h-80 flex items-center justify-center">
            <div className="text-center">
              <svg className="w-10 h-10 text-navy/20 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              <p className="text-navy/40 text-sm font-medium">Map — Sotogrande, Andalusia, Spain</p>
              <p className="text-navy/30 text-xs mt-1">Google Maps embed will be added here</p>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="py-16 lg:py-24">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-10">
            <p className="text-gold font-semibold text-sm tracking-widest uppercase mb-3">
              FAQ
            </p>
            <h2
              className="text-2xl sm:text-3xl font-bold text-navy"
              style={{ fontFamily: "var(--font-playfair), serif" }}
            >
              Frequently Asked Questions
            </h2>
          </div>
          <FAQ items={faqs} />
        </div>
      </section>

      {/* CTA */}
      <section className="py-16 lg:py-20 bg-navy text-white text-center">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <h2
            className="text-2xl sm:text-3xl font-bold mb-4"
            style={{ fontFamily: "var(--font-playfair), serif" }}
          >
            Still Have Questions?
          </h2>
          <p className="text-white/70 mb-6">
            Email us at{" "}
            <span className="text-gold font-semibold">info@sotograndepolo.com</span>{" "}
            or call{" "}
            <span className="text-gold font-semibold">+34 XXX XXX XXX</span>.
            We&apos;re here to help.
          </p>
        </div>
      </section>
    </>
  );
}
