import Link from "next/link";

export default function Footer() {
  return (
    <footer className="bg-navy text-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-10">
          {/* Brand */}
          <div>
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-full bg-gold flex items-center justify-center">
                <span className="text-navy font-bold text-sm">SP</span>
              </div>
              <div className="leading-tight">
                <span className="block font-bold text-sm tracking-wide">
                  Sotogrande Polo
                </span>
                <span className="block text-gold text-[10px] tracking-widest uppercase">
                  Tourism
                </span>
              </div>
            </div>
            <p className="text-white/60 text-sm leading-relaxed">
              Premium polo experiences in Sotogrande, Andalusia. From beginner
              discovery sessions to full week immersions — no experience required.
            </p>
          </div>

          {/* Packages */}
          <div>
            <h3 className="font-semibold text-sm tracking-wide uppercase mb-4 text-gold">
              Packages
            </h3>
            <ul className="space-y-2">
              {[
                { href: "/packages/discovery", label: "Polo Discovery — €199" },
                { href: "/packages/weekend", label: "Weekend Package — €599" },
                { href: "/packages/week-immersion", label: "Week Immersion — €1,499" },
                { href: "/packages/corporate", label: "Corporate Events — €2,500" },
                { href: "/packages/lessons", label: "Private Lessons — €150/hr" },
              ].map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="text-white/60 hover:text-white text-sm transition-colors"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Company */}
          <div>
            <h3 className="font-semibold text-sm tracking-wide uppercase mb-4 text-gold">
              Company
            </h3>
            <ul className="space-y-2">
              {[
                { href: "/about", label: "About Us" },
                { href: "/packages", label: "All Packages" },
                { href: "/contact", label: "Contact" },
                { href: "/contact#faq", label: "FAQ" },
              ].map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="text-white/60 hover:text-white text-sm transition-colors"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Contact */}
          <div>
            <h3 className="font-semibold text-sm tracking-wide uppercase mb-4 text-gold">
              Contact
            </h3>
            <ul className="space-y-3 text-sm text-white/60">
              <li className="flex items-start gap-2">
                <svg className="w-4 h-4 mt-0.5 shrink-0 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
                Sotogrande, Andalusia, Spain
              </li>
              <li className="flex items-start gap-2">
                <svg className="w-4 h-4 mt-0.5 shrink-0 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                info@sotograndepolo.com
              </li>
              <li className="flex items-start gap-2">
                <svg className="w-4 h-4 mt-0.5 shrink-0 text-gold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
                </svg>
                +34 XXX XXX XXX
              </li>
            </ul>
            {/* Social */}
            <div className="flex gap-3 mt-5">
              {["Instagram", "Facebook", "YouTube"].map((platform) => (
                <a
                  key={platform}
                  href="#"
                  aria-label={platform}
                  className="w-9 h-9 rounded-full bg-white/10 hover:bg-gold/80 flex items-center justify-center transition-colors"
                >
                  <span className="text-xs font-semibold">
                    {platform[0]}
                  </span>
                </a>
              ))}
            </div>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="mt-12 pt-8 border-t border-white/10 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-white/40">
          <p>&copy; {new Date().getFullYear()} Sotogrande Polo Tourism. All rights reserved.</p>
          <p>
            Partners:{" "}
            <span className="text-white/60">Polo Valley</span> &middot;{" "}
            <span className="text-white/60">Santa Maria Polo Club</span>
          </p>
        </div>
      </div>
    </footer>
  );
}
