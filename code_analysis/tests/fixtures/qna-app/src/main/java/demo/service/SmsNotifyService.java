package demo.service;

@Service
public class SmsNotifyService implements NotifyService {
    @Override
    public void send(String to) {
        System.out.println("sms " + to);
    }
}
