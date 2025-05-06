import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useState } from "react";

export default function KirillChessSite() {
  const [date, setDate] = useState(new Date());

  return (
    <main className="p-6 space-y-6">
      <section className="text-center">
        <h1 className="text-3xl font-bold">Kirill’s Chess Journey</h1>
        <p className="text-lg text-gray-600">Tracking progress, goals, and tournaments</p>
      </section>

      <Tabs defaultValue="profile" className="w-full">
        <TabsList className="grid grid-cols-4">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="tournaments">Tournaments</TabsTrigger>
          <TabsTrigger value="calendar">Calendar</TabsTrigger>
          <TabsTrigger value="media">Media</TabsTrigger>
        </TabsList>

        <TabsContent value="profile">
          <Card>
            <CardContent className="p-4 space-y-2">
              <h2 className="text-xl font-semibold">About Kirill</h2>
              <p>Age: 11</p>
              <p>Current Ratings:</p>
              <ul className="list-disc list-inside">
                <li>FQE: 1180 (goal: 1900 by end of 2026)</li>
                <li>CFC: 1500</li>
                <li>FIDE: Not yet rated</li>
              </ul>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tournaments">
          <Card>
            <CardContent className="p-4 space-y-4">
              <h2 className="text-xl font-semibold">Upcoming Tournaments</h2>
              <ul className="space-y-2">
                <li>
                  <strong>Capablanca Memorial</strong><br />
                  Varadero, Cuba — May 11–14, 2025<br />
                  Contact: Federación Cubana de Ajedrez<br />
                  Hotel: TBD
                </li>
              </ul>
              <h2 className="text-xl font-semibold">Past Tournaments</h2>
              <ul className="space-y-2">
                <li>
                  <strong>Championnat Jeunesse Rive-Sud</strong><br />
                  March 2025 — Score: 4.5/6<br />
                  Performance Rating: 1320
                </li>
              </ul>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="calendar">
          <Card>
            <CardContent className="p-4">
              <Calendar mode="single" selected={date} onSelect={setDate} className="rounded-md border" />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="media">
          <Card>
            <CardContent className="p-4 space-y-2">
              <h2 className="text-xl font-semibold">Media</h2>
              <p>Coming soon: Game replays, certificates, and photos from tournaments</p>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </main>
  );
}
