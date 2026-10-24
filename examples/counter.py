"""Native Termux:GUI counter, using only the small Kivy-style public API."""
from termux_kivy import App, BoxLayout, Button, Label


class CounterApp(App):
    def build(self):
        self.count = 0
        container = BoxLayout(orientation="vertical")
        self.label = container.add_widget(Label(text="Count: 0", font_size=24))
        button = container.add_widget(Button(text="Increment"))
        button.bind(on_press=self.increment)
        return container

    def increment(self, _button):
        self.count += 1
        self.label.text = f"Count: {self.count}"


if __name__ == "__main__":
    CounterApp().run()
