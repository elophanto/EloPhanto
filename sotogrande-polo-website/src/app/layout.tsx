import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://sotograndepolo.com"),
  title: {
    default: "Sotogrande Polo Tourism | Polo Holidays in Spain",
    template: "%s | Sotogrande Polo Tourism",
  },
  description:
    "Experience polo in Sotogrande, Spain. Beginner-friendly packages from €199. Discovery sessions, weekend breaks, week immersions, corporate events, and private lessons. No experience required.",
  keywords: [
    "polo holidays spain",
    "polo lessons sotogrande",
    "horse riding holidays andalucia",
    "equestrian tourism spain",
    "polo experience sotogrande",
    "luxury equestrian tourism",
    "polo vacation spain",
    "beginner polo spain",
  ],
  authors: [{ name: "Sotogrande Polo Tourism" }],
  openGraph: {
    type: "website",
    locale: "en_GB",
    url: "https://sotograndepolo.com",
    siteName: "Sotogrande Polo Tourism",
    title: "Sotogrande Polo Tourism | Polo Holidays in Spain",
    description:
      "Experience polo in Sotogrande, Spain. Beginner-friendly packages from €199. No experience required.",
    images: [
      {
        url: "https://images.unsplash.com/photo-1565128939020-0f18a5c0960e?w=1200&q=80",
        width: 1200,
        height: 630,
        alt: "Polo in Sotogrande, Spain",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Sotogrande Polo Tourism | Polo Holidays in Spain",
    description:
      "Experience polo in Sotogrande, Spain. Beginner-friendly packages from €199.",
  },
  robots: {
    index: true,
    follow: true,
  },
  alternates: {
    canonical: "https://sotograndepolo.com",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": ["LocalBusiness", "SportsActivityLocation"],
              name: "Sotogrande Polo Tourism",
              description:
                "Premium polo experiences in Sotogrande, Spain. Beginner-friendly packages from €199.",
              url: "https://sotograndepolo.com",
              telephone: "+34 XXX XXX XXX",
              email: "info@sotograndepolo.com",
              address: {
                "@type": "PostalAddress",
                addressLocality: "Sotogrande",
                addressRegion: "Andalusia",
                postalCode: "11310",
                addressCountry: "ES",
              },
              geo: {
                "@type": "GeoCoordinates",
                latitude: 36.2854,
                longitude: -5.2817,
              },
              priceRange: "€€",
              openingHoursSpecification: {
                "@type": "OpeningHoursSpecification",
                dayOfWeek: [
                  "Monday",
                  "Tuesday",
                  "Wednesday",
                  "Thursday",
                  "Friday",
                  "Saturday",
                  "Sunday",
                ],
                opens: "09:00",
                closes: "20:00",
              },
              sameAs: [],
              offers: [
                {
                  "@type": "Offer",
                  name: "Polo Discovery Experience",
                  price: "199.00",
                  priceCurrency: "EUR",
                  availability: "https://schema.org/InStock",
                },
                {
                  "@type": "Offer",
                  name: "Polo Weekend Package",
                  price: "599.00",
                  priceCurrency: "EUR",
                  availability: "https://schema.org/InStock",
                },
                {
                  "@type": "Offer",
                  name: "Polo Week Immersion",
                  price: "1499.00",
                  priceCurrency: "EUR",
                  availability: "https://schema.org/InStock",
                },
                {
                  "@type": "Offer",
                  name: "Corporate Team Building",
                  price: "2500.00",
                  priceCurrency: "EUR",
                  availability: "https://schema.org/InStock",
                },
                {
                  "@type": "Offer",
                  name: "Private Polo Lessons",
                  price: "150.00",
                  priceCurrency: "EUR",
                  availability: "https://schema.org/InStock",
                },
              ],
            }),
          }}
        />
      </head>
      <body className={`${inter.variable} ${playfair.variable} antialiased`}>
        <Header />
        <main className="pt-16 lg:pt-20">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
