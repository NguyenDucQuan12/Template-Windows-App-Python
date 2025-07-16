import customtkinter
from PIL import Image
import logging
from itertools import count

# Mở comment 3 dòng bên dưới mỗi khi test (Chạy trực tiếp hàm if __main__)
import os,sys
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_DIR)

# Các thư viện import từ thư mục tự tạo đặt bắt đầu từ đây
from utils.resource import resource_path



# Ghi lại nhật ký hoạt động
logger = logging.getLogger(__name__)



class LoadingGifLabel(customtkinter.CTkLabel):
    """
    Label hiển thị gif với customtkinter
    """
    def __init__(self, master=None, background_color="#3cb371", resize=None, text = '', **kwargs):
        super().__init__(master, **kwargs)

        # Cài đặt màu nền của gif
        # self.background_color = background_color
        self.configure(text = text,fg_color = background_color )
        # self.configure(bg=background_color)

        # Biến chứa kích thước và các khung hình của gif
        self.resize = resize  
        self.frames = []  
        self.loc = 0
        
        # Biến chứa cửa sổ cha
        self.parent = master
        
    def load(self, im):
        """
        Tải gif và hiển thị lên label theo vòng lặp
        """
        if isinstance(im, str):
            """
            Đọc các frame của gif từ đường dẫn được cung cấp
            """
            im = Image.open(im)

        # Prepare list to store frames
        self.frames = []
        try:
            for i in count(1):
                frame = im.copy()
                # Sử dụng hình ảnh bằng ctkImage và đặt tham số kích thước, nếu không mặc định kích thước là (30,30)
                if self.resize:
                    ctk_img = customtkinter.CTkImage(frame, size=self.resize)

                # Thêm các khung hình của GIF vào biến lưu trữ
                self.frames.append(ctk_img)
                im.seek(i)
        except EOFError:
            pass

        try:
            self.delay = im.info['duration']
        except:
            self.delay = 100

        if len(self.frames) == 1:
            self.config(image=self.frames[0])
        else:
            self.next_frame()

    def unload(self):
        """
        Gọi hàm giải phóng tài nguyên gif trước khi kết thúc để đảm bảo ko lưu trữ các hình ảnh của gif
        """
        # Giải phóng các frame CTkImage
        for frame in self.frames:
            del frame  # Xóa tham chiếu tới từng frame CTkImage

        self.frames = [] 
        self.loc = 0  

        # Giải phóng các tài nguyên khác (nếu có)
        if hasattr(self, 'resize'):
            del self.resize  # Xóa kích thước resize nếu không còn cần thiết

        if hasattr(self, 'delay'):
            del self.delay  # Xóa thời gian trễ nếu không còn cần thiết

    def next_frame(self):
        """
        Hiển thị khung hình tiếp theo trong ảnh GIF
        """
        if self.frames:
            self.loc += 1
            self.loc %= len(self.frames)
            self.configure(image=self.frames[self.loc])
            self.after(self.delay, self.next_frame)
    
    def show_loading_popup_gif(self):
        """
        Hiển thị popup với tệp gif.
        """
        # Tạo label hiển thị gif
        self.pack(fill='both', expand=True, padx = 2, pady = 2)
        self.load(resource_path("assets\\images\\loading\\loading_gif.gif"))

        # Khóa cửa sổ chính để chỉ có thể tương tác với cửa sổ con
        self.parent.wm_attributes("-disabled", True)  
        self.grab_set()  # Vô hiệu hóa các cửa sổ khác trong khi tải

    def hide_loading_popup_gif(self):
        """
        Ẩn popup khi tải xong.
        """
        self.parent.wm_attributes("-disabled", False)  # Bật lại cửa sổ chính
        if hasattr(self, 'loading_popup'):
            # Gọi unload để giải phóng tài nguyên GIF trước khi đóng popup
            if hasattr(self, 'unload'):
                self.unload()

            # Đảm bảo rằng loading_label được hủy bỏ đúng cách trước khi đóng popup
            self.destroy()
            del self  # Xóa tham chiếu tới label GIF

            # Destroy popup
            self.destroy() 
            del self  # Xóa tham chiếu tới cửa sổ popup


if __name__ == "__main__":
    # Create the root window using customtkinter
    root = customtkinter.CTk()

    # Cập nhật vị trí cửa sổ ở giữa màn hình chính
    root.geometry(f'900x900')

    # Set the desired resize dimensions (e.g., 150x150)
    resize_dimensions = (150, 150)
    
    # Create the customtkinter label with resizing option
    lbl = LoadingGifLabel(root, resize=resize_dimensions)
    lbl.show_loading_popup_gif()
    
    # Run the main loop
    root.mainloop()