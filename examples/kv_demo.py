"""KV subset example: no arbitrary Python execution in the KV parser."""
from termux_kivy import App, Builder


class KvDemo(App):
    def build(self):
        return Builder.load_string("""
BoxLayout:
    orientation: 'vertical'
    Label:
        id: output
        text: 'Termux:GUI'
    Button:
        text: 'Tap me'
        on_press: app.tapped()
""")

    def tapped(self):
        self.root.ids["output"].text = "The button works!"


if __name__ == "__main__":
    KvDemo().run()
