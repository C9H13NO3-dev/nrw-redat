module.exports = {
  content: ["./redat/templates/**/*.html", "./redat/static/*.js"],
  theme: { screens: { xs: "400px", sm: "640px", md: "768px", lg: "1024px", xl: "1280px" } },
  safelist: [
    // dynamic classes produced in redat.js / analysis.js
    "bg-red-100", "text-red-700", "text-red-800", "bg-yellow-100", "text-yellow-700", "text-yellow-800",
    "bg-green-100", "text-green-700", "text-green-800", "bg-orange-100", "text-orange-800",
    "bg-gray-100", "text-gray-700", "text-gray-800", "bg-blue-100", "text-blue-800",
    "bg-amber-50", "text-amber-800", "border-amber-200", "bg-sky-50", "text-sky-800", "border-sky-200",
    "bg-blue-100", "border-blue-500", "bg-white", "border-gray-200",
  ],
};
